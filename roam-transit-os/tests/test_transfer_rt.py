import yaml

from roam.exports import gtfs_realtime
from roam.exports.gtfs_import import load_stops
from roam.models import Mode, Rider, TripStatus

from .conftest import SERVICE_DAY, new_city_config

STOPS = """stop_id,stop_name,stop_lat,stop_lon,location_type
S1,Main St Station,40.08,-74.98,0
S2,Far Away,40.50,-74.50,0
P1,Platform 1,40.08,-74.98,1
"""


def _tenant_with_gtfs(tmp_path):
    from roam.platform import Platform

    (tmp_path / "gtfs").mkdir()
    (tmp_path / "gtfs" / "stops.txt").write_text(STOPS)
    cfg = new_city_config(gtfs_feed="gtfs")
    (tmp_path / "t.yaml").write_text(yaml.safe_dump(cfg))
    p = Platform(today=SERVICE_DAY)
    rt = p.provision(tmp_path / "t.yaml")
    return p, rt


def test_load_stops_skips_stations_and_platforms(tmp_path):
    (tmp_path / "stops.txt").write_text(STOPS)
    stops = load_stops(tmp_path)
    assert [s["stop_id"] for s in stops] == ["S1", "S2"]
    assert stops[0]["lat"] == 40.08 and stops[0]["lon"] == -74.98


def test_out_of_zone_destination_books_transfer_to_fixed_route(tmp_path):
    p, rt = _tenant_with_gtfs(tmp_path)
    assert len(rt.gtfs_stops) == 2
    p.clock.minute = 600
    r = p.store.scope("testville").add(Rider(id="r1", tenant_id="testville"))
    t = p.booking.request_trip("testville", r.id, Mode.microtransit, (-75.05, 40.06), (-74.6, 40.4), SERVICE_DAY, 600)
    assert t.status == TripStatus.booked
    assert t.destination == (-74.98, 40.08) and "Main St Station" in t.status_reason  # in-zone stop, not the far one


def test_trip_updates_feed_has_etas_for_booked_trips(testville):
    p, rt = testville
    p.clock.minute = 600
    r = p.store.scope("testville").add(Rider(id="r1", tenant_id="testville", eligibility_status="certified"))
    t = p.booking.request_trip("testville", r.id, Mode.paratransit, (-75.05, 40.06), (-75.0, 40.03), SERVICE_DAY, 600)
    feed = gtfs_realtime.trip_updates(p, "testville", SERVICE_DAY)
    ent = {e["id"]: e for e in feed["entity"]}
    assert t.id in ent
    stu = ent[t.id]["trip_update"]["stop_time_update"]
    assert stu and stu[0]["arrival"]["time"] > 0
    assert "vehicle" not in ent[t.id]["trip_update"]  # no nulls in the feed before a vehicle is assigned
