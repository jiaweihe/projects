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


def test_malformed_config_is_a_422_not_a_500(platform):
    c = _client(platform)
    bad_type = new_city_config(type="spaceport")
    for body in (yaml.safe_dump(bad_type), "just a string", "- a\n- list", "{unclosed: [", ""):
        r = c.post("/tenants", content=body, headers=OPS)
        assert r.status_code == 422, (body[:30], r.status_code, r.text[:200])
    r = c.post("/tenants/validate", json={"id": "x"}, headers=OPS)
    assert r.status_code == 422


def test_reprovisioning_an_existing_tenant_is_refused(platform):
    c = _client(platform)  # testville already provisioned
    r = c.post("/tenants", content=yaml.safe_dump(new_city_config(name="Hijacked")), headers=OPS)
    assert r.status_code == 409
    assert platform.tenant("testville").config.name == "Testville"


def test_schema_error_with_yaml_date_still_returns_422(platform):
    c = _client(platform)
    r = c.post(
        "/tenants",
        content=yaml.safe_dump(new_city_config(id="dated", phase="2026-01-01")).replace("'2026-01-01'", "2026-01-01"),
        headers=OPS,
    )
    assert r.status_code == 422


def test_raw_export_downloads_a_zip_and_leaves_nothing_on_the_server(platform, tmp_path, monkeypatch):
    import io
    import zipfile

    monkeypatch.chdir(tmp_path)
    c = _client(platform)
    rider = c.post("/tenants/testville/riders", json={"eligibility_status": "certified", "phone": "+15550009999"}, headers=OPS).json()
    c.post("/tenants/testville/trips", headers=OPS, json={"rider_id": rider["id"], **TRIP})
    r = c.post("/tenants/testville/exports/raw", headers={"X-Api-Key": "city-tv"}, params={"include_pii": True})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"manifest.json", "triprequest.csv", "rider.csv"} <= names
    assert "+15550009999" in z.read("rider.csv").decode()  # the city asked for PII and gets it
    assert not any(tmp_path.rglob("*.csv"))  # ...but none of it is left on the API host
    ops = c.post("/tenants/testville/exports/raw", headers=OPS)
    assert "+15550009999" not in zipfile.ZipFile(io.BytesIO(ops.content)).read("rider.csv").decode()


def test_driver_app_reports_breakdown_and_position(platform):
    c = _client(platform)
    rider = c.post("/tenants/testville/riders", json={"eligibility_status": "certified"}, headers=OPS).json()
    trip = c.post("/tenants/testville/trips", headers=OPS, json={"rider_id": rider["id"], **TRIP}).json()
    c.post(f"/tenants/testville/days/{SERVICE_DAY}/start", headers=OPS)
    d = platform.dispatcher("testville", SERVICE_DAY)
    vid = next(u.vehicle_id for u in d.units if any(n.trip_id == trip["id"] for n in u.route))
    r = c.post(f"/driver/{vid}/telemetry", headers=OPS, json={"location": [-75.04, 40.05], "time": "08:30", "speed_kmh": 20})
    assert r.status_code == 200
    assert any(v["vehicle_id"] == vid for v in c.get("/ops/map", headers=OPS).json())
    r = c.post(f"/driver/{vid}/fault", headers=OPS, json={"location": [-75.04, 40.05], "time": "08:40", "reason": "engine light"})
    assert r.status_code == 200
    faults = [e for e in platform.ops.exceptions.values() if e.type == "vehicle_fault" and e.vehicle_id == vid]
    assert len(faults) == 1
    assert all(n.trip_id != trip["id"] for u in d.units if u.vehicle_id == vid for n in u.route)  # moved off the broken van


def test_driver_times_are_validated(platform):
    c = _client(platform)
    c.post(f"/tenants/testville/days/{SERVICE_DAY}/start", headers=OPS)
    for bad in ("abc", "25:00", "9:7:1", "12:60"):
        r = c.post("/driver/testville:TV01/telemetry", headers=OPS, json={"location": [-75.04, 40.05], "time": bad})
        assert r.status_code == 422, bad


def test_driver_positions_validated_and_duplicate_fault_alerts_once(platform):
    c = _client(platform)
    c.post(f"/tenants/testville/days/{SERVICE_DAY}/start", headers=OPS)
    assert c.post("/driver/testville:TV01/telemetry", headers=OPS, json={"location": [500, 500]}).status_code == 422
    body = {"location": [-75.04, 40.05], "reason": "flat", "time": "09:00"}
    c.post("/driver/testville:TV01/fault", headers=OPS, json=body)
    c.post("/driver/testville:TV01/fault", headers=OPS, json=body)  # driver taps twice
    assert len([e for e in platform.ops.exceptions.values() if e.type == "vehicle_fault"]) == 1
