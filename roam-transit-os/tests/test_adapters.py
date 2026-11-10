from roam.adapters.av_partner import AVPartnerAdapter, SimulatedAVProvider
from roam.adapters.base import AssistContext, VehicleEvent
from roam.adapters.human_driver import HumanDriverAdapter
from roam.adapters.simulator import SimulatorAdapter
from roam.geo import HaversineTravelModel
from roam.models import Run, Stop, StopType, VehicleCapabilities
from roam.sim.world import SimWorld

CAPS = VehicleCapabilities(seats=8, wheelchair_positions=1)
ODD = {"type": "Polygon", "coordinates": [[[-75.1, 40.0], [-75.0, 40.0], [-75.0, 40.1], [-75.1, 40.1], [-75.1, 40.0]]]}


def _run(loc_a=(-75.05, 40.05), loc_b=(-75.02, 40.06)):
    return Run(id="run1", tenant_id="t", shift_id="s", vehicle_id="v1", stops=[
        Stop(id="trip1:pu", run_id="run1", trip_request_id="trip1", type=StopType.pickup, location=loc_a, earliest=480, latest=510),
        Stop(id="trip1:do", run_id="run1", trip_request_id="trip1", type=StopType.dropoff, location=loc_b, earliest=0, latest=2000),
    ])


def test_human_driver_manifest_and_securement_checklist():
    a = HumanDriverAdapter("t:v1", CAPS)
    events: list[VehicleEvent] = []
    a.on_event(events.append)
    a.assign_run(_run())
    assert [s["id"] for s in a.manifest()["stops"]] == ["trip1:pu", "trip1:do"]
    assert a.driver_action("trip1:pu", "arrive", 482).ok
    refused = a.driver_action("trip1:pu", "board", 484, wheelchair=True, checklist={"four_point_tiedowns_attached": True})
    assert not refused.ok and "checklist" in refused.message
    full = {k: True for k in ("four_point_tiedowns_attached", "lap_and_shoulder_belt_offered", "wheelchair_brakes_set", "ramp_or_lift_stowed")}
    assert a.driver_action("trip1:pu", "board", 486, wheelchair=True, checklist=full).ok
    assert a.driver_action("trip1:do", "no_show", 500).ok is False  # no-show only at a pickup
    assert [e.type for e in events] == ["arrival", "boarding"]


def test_simulator_executes_run_in_order():
    w = SimWorld(seed=1)
    sim = SimulatorAdapter("v1", CAPS, w, HaversineTravelModel(), (-75.03, 40.05))
    sim.params.no_show_rate = 0.0
    seen = []
    sim.on_event(lambda e: seen.append((e.type, e.stop_id)))
    sim.assign_run(_run())
    w.run_until(1000)
    kinds = [k for k, _ in seen if k in ("boarding", "dropoff")]
    assert kinds == ["boarding", "dropoff"]
    boarding_t = next(t for t in [s for s in sim._finished["run1"].stops] if t.type == StopType.pickup).actual
    assert boarding_t is not None


def test_av_adapter_enforces_odd_and_raises_remote_assist():
    w = SimWorld()
    sim = SimulatorAdapter("v1", CAPS, w, HaversineTravelModel(), (-75.03, 40.05))
    tickets = []
    av = AVPartnerAdapter("v1", CAPS, SimulatedAVProvider({"v1": sim}), {"odd": ODD}, on_assist=lambda ctx, t: tickets.append(t))
    assert av.assign_run(_run()).ok
    bad = av.assign_run(_run(loc_b=(-74.5, 40.5)))
    assert not bad.ok and "operational design domain" in bad.message
    t = av.request_remote_assist(AssistContext("v1", 500, (-75.05, 40.05), "blocked lane"))
    assert tickets == [t]


def test_remote_assist_lands_in_ops_queue(platform):
    from .conftest import TENANTS

    platform.provision(TENANTS / "austin_tx.yaml")
    w = SimWorld()
    adapters = platform.build_adapters("austin_tx", w)
    av = next(a for a in adapters.values() if isinstance(a, AVPartnerAdapter))
    av.request_remote_assist(AssistContext(av.vehicle_id, 600, (-97.74, 30.27), "construction zone"))
    q = platform.ops.queue(tenant_ids={"austin_tx"})
    assert q and q[0].type == "remote_assist" and q[0].severity == 2
