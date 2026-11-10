import yaml
from fastapi.testclient import TestClient

from roam.api import Principal, create_app

from .conftest import SERVICE_DAY, new_city_config

OPS = {"X-Api-Key": "ops"}
TRIP = {
    "mode": "paratransit",
    "origin": [-75.05, 40.06],
    "destination": [-75.0, 40.03],
    "service_date": SERVICE_DAY.isoformat(),
    "time": "09:00",
}


def _client(platform):
    keys = {
        "ops": Principal("ops", None, "seat-1"),
        "city-tv": Principal("city", {"testville"}),
        "city-other": Principal("city", {"othertown"}),
        "rider-tv": Principal("rider", {"testville"}),
    }
    c = TestClient(create_app(platform, keys, realtime_clock=False))
    assert c.post("/tenants", content=yaml.safe_dump(new_city_config()), headers=OPS).status_code == 201
    other = new_city_config(id="othertown", name="Othertown", region={"state": "PA", "jurisdiction": "Othertown"})
    assert c.post("/tenants", content=yaml.safe_dump(other), headers=OPS).status_code == 201
    platform.clock.minute = 600
    return c


def test_provision_book_and_isolation(platform):
    c = _client(platform)
    rider = c.post("/tenants/testville/riders", json={"eligibility_status": "certified"}, headers={"X-Api-Key": "rider-tv"}).json()
    trip = c.post("/tenants/testville/trips", headers={"X-Api-Key": "rider-tv"}, json={"rider_id": rider["id"], **TRIP}).json()
    assert trip["status"] == "booked"
    # another city cannot see this tenant (404, not 403: no existence leak)
    assert c.get(f"/tenants/testville/trips/{trip['id']}", headers={"X-Api-Key": "city-other"}).status_code == 404
    assert (
        c.get("/tenants/testville/kpis", params={"start": SERVICE_DAY, "end": SERVICE_DAY}, headers={"X-Api-Key": "city-tv"}).status_code
        == 200
    )
    assert c.get("/ops/queue", headers={"X-Api-Key": "city-tv"}).status_code == 403
    assert c.post("/tenants", content="id: x", headers={"X-Api-Key": "city-tv"}).status_code == 403
    assert c.get("/tenants/testville/exports/gtfs-flex.zip", headers={"X-Api-Key": "city-tv"}).headers["content-type"] == "application/zip"
    assert c.get("/tenants/testville", headers={"X-Api-Key": "nope"}).status_code == 401
    assert c.get("/").status_code == 200


def test_rejects_excluded_jurisdiction(platform):
    c = _client(platform)
    jc = new_city_config(id="jc", name="Jersey City", region={"state": "NJ", "jurisdiction": "Jersey City"})
    r = c.post("/tenants", content=yaml.safe_dump(jc), headers=OPS)
    assert r.status_code == 422 and "excluded" in r.text


def test_driver_app_flow(platform):
    c = _client(platform)
    rider = c.post("/tenants/testville/riders", json={"eligibility_status": "certified"}, headers=OPS).json()
    trip = c.post("/tenants/testville/trips", headers=OPS, json={"rider_id": rider["id"], **TRIP}).json()
    assert c.post(f"/tenants/testville/days/{SERVICE_DAY}/start", headers=OPS).status_code == 200
    d = platform.dispatcher("testville", SERVICE_DAY)
    unit = next(u for u in d.units if any(n.trip_id == trip["id"] for n in u.route))
    m = c.get(f"/driver/{unit.vehicle_id}/manifest", headers=OPS).json()
    pu, do = (s["id"] for s in m["stops"] if s["trip_request_id"] == trip["id"])
    steps = [
        (pu, "depart", "08:45"),
        (pu, "arrive", "09:05"),
        (pu, "board", "09:07"),
        (do, "depart", "09:08"),
        (do, "arrive", "09:20"),
        (do, "dropoff", "09:21"),
    ]
    for sid, act, t in steps:
        r = c.post(f"/driver/{unit.vehicle_id}/actions", headers=OPS, json={"stop_id": sid, "action": act, "time": t})
        assert r.status_code == 200, r.text
    t = c.get(f"/tenants/testville/trips/{trip['id']}", headers=OPS).json()
    assert t["status"] == "completed" and t["actual_pickup"] == 9 * 60 + 7
