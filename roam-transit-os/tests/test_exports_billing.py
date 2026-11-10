import csv
import io
import json

import pytest

from roam.billing import build_invoice, performance_adjustment
from roam.config.schema import PerformanceTerms
from roam.exports import gtfs_flex, gtfs_realtime, mds, ntd, raw
from roam.sim.demand import DemandSpec
from roam.sim.runner import simulate_day

from .conftest import SERVICE_DAY


@pytest.fixture
def simulated(testville):
    p, rt = testville
    simulate_day(p, SERVICE_DAY, {"testville": DemandSpec(paratransit_trips=30, microtransit_trips=20)}, seed=3)
    return p, rt


def test_gtfs_flex_files(testville):
    p, rt = testville
    files = gtfs_flex.build_gtfs_flex(rt)
    assert {"agency.txt", "routes.txt", "trips.txt", "stop_times.txt", "booking_rules.txt", "calendar.txt", "locations.geojson"} <= set(
        files
    )
    st = list(csv.DictReader(io.StringIO(files["stop_times.txt"])))
    assert st and all(r["start_pickup_drop_off_window"] and r["location_id"] for r in st)
    br = {r["booking_rule_id"]: r for r in csv.DictReader(io.StringIO(files["booking_rules.txt"]))}
    assert br["br_paratransit"]["booking_type"] == "2" and br["br_microtransit"]["booking_type"] == "0"
    loc_ids = {f["id"] for f in json.loads(files["locations.geojson"])["features"]}
    assert {r["location_id"] for r in st} <= loc_ids


def test_realtime_mds_ntd_raw(simulated, tmp_path):
    p, rt = simulated
    vp = gtfs_realtime.vehicle_positions(p, "testville", SERVICE_DAY)
    assert vp["header"]["gtfs_realtime_version"] == "2.0" and vp["entity"]
    ev = mds.mds_events(p, "testville", SERVICE_DAY)["events"]
    assert ev and all("event_types" in e and "timestamp" in e for e in ev)
    trips = mds.mds_trips(p, "testville", SERVICE_DAY)["trips"]
    assert trips and "rider_id" not in json.dumps(trips)
    row = ntd.ntd_monthly(p, "testville", SERVICE_DAY, SERVICE_DAY)
    assert row["mode"] == "DR" and row["upt"] > 0 and row["vrh"] > 0 and row["voms"] > 0
    man = raw.export_tenant(p, "testville", tmp_path)
    assert man["tables"]["TripRequest"]["rows"] > 0
    rider_csv = (tmp_path / "testville" / "rider.csv").read_text()
    assert "+1555" not in rider_csv  # PII excluded by default


def test_invoice_is_platform_plus_hours_plus_performance(simulated):
    p, rt = simulated
    inv = build_invoice(p, "testville", "2026-11", SERVICE_DAY, SERVICE_DAY)
    pr = rt.config.pricing
    assert inv.platform_fee == pytest.approx(4 * pr.platform_fee_per_vehicle_month / 30, rel=1e-3)
    assert inv.ops_fee == pytest.approx(inv.revenue_hours * pr.ops_fee_per_vrh, abs=0.01)
    assert inv.total == pytest.approx(inv.platform_fee + inv.ops_fee + inv.performance_adj, abs=0.01)


def test_performance_adjustment_capped_and_ada_penalty():
    t = PerformanceTerms()
    great = {"on_time_performance": 1.0, "wait_p95_min": 0, "complaints_per_1k_trips": 0, "cost_per_trip": 0, "ada_denials": 0}
    adj, d = performance_adjustment(great, t, 10_000)
    assert adj == pytest.approx(1_000) and d["total_pct"] == t.cap_pct
    adj, d = performance_adjustment({**great, "ada_denials": 1}, t, 10_000)
    assert adj < 1_000 and "ada_denials" in d


@pytest.mark.parametrize("period", ["2026-13", "abc", "2026", "2026-1-1"])
def test_bad_invoice_period_is_rejected_cleanly(testville, period):
    from fastapi.testclient import TestClient

    from roam.api import Principal, create_app

    p, rt = testville
    c = TestClient(create_app(p, {"city": Principal("city", {"testville"})}, realtime_clock=False))
    r = c.post(f"/tenants/testville/invoices/{period}", headers={"X-Api-Key": "city"})
    assert r.status_code == 422, (period, r.status_code)


def test_invoice_rejects_range_outside_period(simulated):
    p, rt = simulated
    with pytest.raises(ValueError):
        build_invoice(p, "testville", "2026-10", SERVICE_DAY, SERVICE_DAY)  # Nov 17 is not in October
