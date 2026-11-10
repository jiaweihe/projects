"""v0.1 acceptance tests (spec §13)."""

import time

import pytest

from roam.config.schema import config_from_dict
from roam.models import TripRequest, TripStatus
from roam.platform import Platform
from roam.sim.demand import DemandSpec
from roam.sim.runner import simulate_day

from .conftest import FIXTURES, SERVICE_DAY, TENANTS, TODAY, new_city_config

TERMINAL = {TripStatus.completed, TripStatus.no_show, TripStatus.cancelled, TripStatus.denied, TripStatus.rejected}


def test_new_tenant_goes_live_from_config_in_under_a_day():
    """A brand-new city: config + zone -> validated, provisioned, GTFS-Flex published and
    a full simulated service day run. The whole thing is machine time in seconds; the
    human setup work is filling in one config file."""
    t0 = time.perf_counter()
    p = Platform(today=TODAY)
    rt = p.provision(config_from_dict(new_city_config()), require_go_live=True)
    assert rt.validation.can_go_live, rt.validation.golive_blockers
    from roam.exports.gtfs_flex import build_gtfs_flex

    assert build_gtfs_flex(rt)["stop_times.txt"]
    res = simulate_day(p, SERVICE_DAY, {"testville": DemandSpec(paratransit_trips=30, microtransit_trips=20)}, seed=2)
    k = res.tenants["testville"]
    assert k["trips_completed"] > 0
    assert time.perf_counter() - t0 < 60  # minutes of setup would already be "under one day"; this is seconds


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_simulated_paratransit_day_zero_denials_otp_above_90(seed):
    p = Platform(today=TODAY)
    p.provision(TENANTS / "mercer_county_nj.yaml")
    res = simulate_day(p, SERVICE_DAY, {"mercer_county_nj": DemandSpec(paratransit_trips=60)}, seed=seed)
    k = res.tenants["mercer_county_nj"]
    assert k["ada_denials"] == 0
    assert k["on_time_performance"] > 0.90
    assert k["trips_completed"] >= 50
    trips = p.store.scope("mercer_county_nj").list(TripRequest)
    assert all(t.status in TERMINAL for t in trips), "every booked trip must be served or closed out"


def test_one_ops_seat_supervises_three_tenants():
    p = Platform(today=TODAY)
    for name in FIXTURES:
        p.provision(TENANTS / f"{name}.yaml")
    seat = p.ops.add_seat("seat-1", "Ops seat 1", set(FIXTURES))
    specs = {
        "mercer_county_nj": DemandSpec(paratransit_trips=60, microtransit_trips=40),
        "austin_tx": DemandSpec(microtransit_trips=60, av_trips=20),
        "miami_dade_fl": DemandSpec(paratransit_trips=80, av_trips=20),
    }
    res = simulate_day(p, SERVICE_DAY, specs, seed=7)
    # inject an AV remote-assist and a vehicle fault so the seat sees every exception class
    from roam.adapters.av_partner import AVPartnerAdapter
    from roam.adapters.base import AssistContext

    av = next(a for a in p.adapters.values() if isinstance(a, AVPartnerAdapter))
    av.request_remote_assist(AssistContext(av.vehicle_id, 12 * 60, (-97.74, 30.27), "double-parked truck"))
    p.ops.raise_exception(type="vehicle_fault", severity=1, tenant_id="miami_dade_fl", at=13 * 60, service_date=SERVICE_DAY,
                          message="injected fault")
    stats = p.ops.simulate_seat("seat-1", 4 * 60 + 45, 23 * 60 + 15, SERVICE_DAY)
    assert stats["tenants"] == 3 and stats["vehicles"] >= 30
    assert stats["utilization"] < 0.5, stats  # one person has headroom
    assert stats.get("p95_response_min_critical", 0) <= 5 and stats.get("p95_response_min_high", 0) <= 10
    assert all(k["tenants_per_ops_seat"] == 3 for k in res.tenants.values())
    assert all(k["wait_p95_min"] < 45 for k in res.tenants.values()), {t: k["wait_p95_min"] for t, k in res.tenants.items()}
    for tid in FIXTURES:
        assert all(t.status in TERMINAL for t in p.store.scope(tid).list(TripRequest))
    assert not p.ops.queue(seat.id)  # everything handled


@pytest.mark.parametrize("name", FIXTURES)
def test_proposal_three_phase_comparison(name, tmp_path):
    from roam.config.schema import load_config
    from roam.proposal.generator import ProposalInput, generate_proposal, write_pdf

    cfg, geoms = load_config(TENANTS / f"{name}.yaml")
    zones = {z.mode.value: geoms[z.id] for z in cfg.zones}
    boundary = zones.get("paratransit") or zones["microtransit"]
    modes = tuple(m for m in ("paratransit", "microtransit") if m in zones)
    inp = ProposalInput(name=cfg.name, state=cfg.region["state"], jurisdiction=cfg.region["jurisdiction"], boundary=boundary,
                        modes=modes, microtransit_boundary=zones.get("microtransit"), depot=tuple(cfg.depot), sample_cap=40)
    prop = generate_proposal(inp)
    for ph in ("phase_1", "phase_2", "phase_3"):
        c = prop["costs"][ph]
        assert c["total"] > 0 and c["cost_per_trip"] > 0
    p1, p3 = prop["costs"]["phase_1"], prop["costs"]["phase_3"]
    assert p1["drivers"] > 0 and "drivers" not in p3 or p3["drivers"] == 0
    assert p3["remote_supervision"] > 0 and p3["av_software_licenses"] > 0  # driverless still has labor/licence costs
    assert prop["benchmark"]["turnkey_low"] < prop["benchmark"]["turnkey_high"]
    assert "av_license_breakeven_per_vehicle_month" in prop["sensitivity"]
    pdf = write_pdf(prop, tmp_path / f"{name}.pdf")
    assert pdf.read_bytes()[:4] == b"%PDF"


def test_proposal_refuses_excluded_jurisdiction():
    from roam.proposal.generator import ProposalInput, generate_proposal

    from .conftest import SQUARE

    with pytest.raises(PermissionError):
        generate_proposal(ProposalInput(name="Jersey City", state="NJ", boundary=SQUARE))
