from roam.dispatch.core import Node, Task, Unit, evaluate, make_break
from roam.dispatch.insertion import InsertionSolver
from roam.geo import HaversineTravelModel

TRAVEL = HaversineTravelModel()
DEPOT = (-75.03, 40.05)


def unit(uid="u1", seats=4, wc=1, start=360, end=900):
    return Unit(uid, "v-" + uid, seats, wc, 400, DEPOT, start, DEPOT, end)


def task(tid, t, wc=0, a=(-75.05, 40.06), b=(-75.00, 40.03), window=25):
    return Task(tid, a, b, t, t + window, 60, seats=0 if wc else 1, wc=wc, pu_service=3, do_service=3)


def test_wheelchair_capacity_enforced():
    u = unit(wc=1)
    t1, t2 = task("a", 480, wc=1), task("b", 480, wc=1, a=(-75.049, 40.061))
    route = [Node.pickup_of(t1), Node.pickup_of(t2), Node.dropoff_of(t1), Node.dropoff_of(t2)]
    assert evaluate(u, route, TRAVEL) is None  # two wheelchairs, one position
    assert evaluate(unit(wc=2), route, TRAVEL) is not None


def test_time_window_and_ride_time():
    u = unit()
    t = task("a", 480)
    ok = evaluate(u, [Node.pickup_of(t), Node.dropoff_of(t)], TRAVEL)
    assert ok and t.pu_earliest <= ok.times[0] <= t.pu_latest
    t.max_ride = 1  # impossible ride-time limit
    assert evaluate(u, [Node.pickup_of(t), Node.dropoff_of(t)], TRAVEL) is None


def test_shift_end_and_break():
    u = unit(end=500)
    t = task("a", 490)
    assert evaluate(u, [Node.pickup_of(t), Node.dropoff_of(t)], TRAVEL) is None  # cannot return before shift end
    u2 = unit()
    u2.route = [make_break(600, 700, 30)]
    s = evaluate(u2, u2.route, TRAVEL)
    assert s.times[0] == 600


def test_insertion_solver_serves_feasible_day():
    units = [unit("u1"), unit("u2")]
    tasks = [task(f"t{i}", 420 + 25 * i, wc=1 if i % 4 == 0 else 0) for i in range(16)]
    sol = InsertionSolver().solve(units, tasks, TRAVEL)
    assert not sol.unassigned
    for u in sol.units:
        assert evaluate(u, u.route, TRAVEL, 1.08) is not None


def test_odd_restriction_respected():
    units = [unit("u1"), unit("u2")]
    t = task("x", 480)
    t.allowed_units = {"u2"}
    ins = InsertionSolver().insert(units, t, TRAVEL)
    assert ins.unit.unit_id == "u2"


def _brute_force(units, t, travel, buffer):
    best = None
    for u in units:
        base = evaluate(u, u.route, travel, buffer)
        if base is None:
            continue
        for i in range(len(u.route) + 1):
            for j in range(i, len(u.route) + 1):
                cand = u.route[:i] + [Node.pickup_of(t)] + u.route[i:j] + [Node.dropoff_of(t)] + u.route[j:]
                s = evaluate(u, cand, travel, buffer)
                if s is not None and (best is None or s.cost - base.cost < best - 1e-9):
                    best = s.cost - base.cost
    return best


def test_pruned_insertion_matches_brute_force_with_fewer_evaluations(monkeypatch):
    import random

    import roam.dispatch.core as core

    rng = random.Random(3)
    solver = InsertionSolver()
    units = [unit("u1", seats=6), unit("u2", seats=6)]
    pts = lambda: (-75.10 + rng.random() * 0.13, 40.0 + rng.random() * 0.1)  # noqa: E731
    for k in range(18):
        solver.insert(units, Task(f"b{k}", pts(), pts(), 400 + 25 * k, 430 + 25 * k, 60), TRAVEL)
    calls = {"n": 0}
    real = core.evaluate

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    for k in range(15):
        probe = Task(f"p{k}", pts(), pts(), 420 + 30 * k, 450 + 30 * k, 60)
        expected = _brute_force(units, probe, TRAVEL, solver.buffer)
        monkeypatch.setattr(core, "evaluate", counting)
        ins = core.best_insertion(units, probe, TRAVEL, solver.buffer)
        monkeypatch.setattr(core, "evaluate", real)
        assert (ins is None) == (expected is None)
        if ins is not None:
            assert abs(ins.delta - expected) < 1e-6
    n_nodes = sum(len(u.route) for u in units)
    full = 15 * sum((len(u.route) + 1) * (len(u.route) + 2) // 2 + 1 for u in units)
    assert calls["n"] < 0.5 * full, (calls["n"], full, n_nodes)


def test_evaluate_at_reports_first_violation():
    from roam.dispatch.core import evaluate_at

    u = unit(end=900)
    t = task("a", 480)
    s, fail = evaluate_at(u, [Node.pickup_of(t), Node.dropoff_of(t)], TRAVEL)
    assert s is not None and fail == -1
    assert evaluate_at(u, [Node.dropoff_of(t), Node.pickup_of(t)], TRAVEL) == (None, 0)  # drop-off before pickup
    late = task("b", 300, window=5)  # window closes before the shift starts
    assert evaluate_at(u, [Node.pickup_of(late), Node.dropoff_of(late)], TRAVEL) == (None, 0)
    short = unit(end=485)
    assert evaluate_at(short, [Node.pickup_of(t), Node.dropoff_of(t)], TRAVEL)[1] == 2  # return-to-depot violation


def test_any_solver_object_can_be_plugged_in_for_batch_planning():
    """Spec §7.3: the solver sits behind an interface (OR-Tools/VROOM can be dropped in)."""
    from datetime import date

    from roam.config.schema import config_from_dict
    from roam.models import EligibilityStatus, Mode, Rider
    from roam.platform import Platform

    from .conftest import new_city_config

    class Recording(InsertionSolver):
        name = "recording"
        calls = 0

        def solve(self, units, tasks, travel):
            Recording.calls += 1
            return super().solve(units, tasks, travel)

    p = Platform(today=date(2026, 11, 16), batch_solver=Recording())
    p.provision(config_from_dict(new_city_config()))
    p.clock.minute = 600
    r = p.store.scope("testville").add(Rider(id="r1", tenant_id="testville", eligibility_status=EligibilityStatus.certified))
    p.booking.request_trip("testville", r.id, Mode.paratransit, (-75.05, 40.06), (-75.0, 40.03), date(2026, 11, 17), 600)
    info = p.start_day("testville", date(2026, 11, 17), p.build_adapters("testville"))
    assert Recording.calls == 1 and info["solver"] in ("recording", "tentative")


def test_vehicle_fault_reassigns_pickups_and_rescues_onboard_riders():
    from datetime import date

    from roam.config.schema import config_from_dict
    from roam.models import EligibilityStatus, Mode, Rider, TripRequest, TripStatus
    from roam.platform import Platform
    from roam.sim.world import SimWorld

    from .conftest import new_city_config

    day = date(2026, 11, 17)
    p = Platform(today=date(2026, 11, 16))
    p.provision(config_from_dict(new_city_config()))
    p.clock.minute = 600
    scope = p.store.scope("testville")
    pts = [(-75.08, 40.02), (-75.0, 40.08), (-75.06, 40.09), (-74.99, 40.01), (-75.04, 40.04)]
    for k in range(12):
        r = scope.add(Rider(id=f"r{k}", tenant_id="testville", eligibility_status=EligibilityStatus.certified))
        p.booking.request_trip("testville", r.id, Mode.paratransit, pts[k % 5], pts[(k + 2) % 5], day, 420 + 20 * k)
    p.clock.today = day
    w = SimWorld(seed=4)
    adapters = p.build_adapters("testville", w)
    for a in adapters.values():
        a.params.no_show_rate = 0.0
    p.start_day("testville", day, adapters)
    trips = scope.list(TripRequest)
    while not any(t.status == TripStatus.onboard for t in trips):
        w.run_until(w.now + 1)
    victim = next(t for t in trips if t.status == TripStatus.onboard)
    broken = victim.vehicle_id
    first_boarding, first_arrival = victim.actual_pickup, victim.pickup_arrival
    adapters[broken].inject_fault("flat tyre")
    w.run_until(26 * 60)

    faults = [e for e in p.ops.exceptions.values() if e.type == "vehicle_fault"]
    assert len(faults) == 1 and faults[0].severity == 1  # rider onboard -> critical
    assert all(t.status == TripStatus.completed for t in trips), [(t.id, t.status) for t in trips]
    assert victim.vehicle_id != broken  # rescued by another vehicle
    # the rescue is not a new pickup: original boarding/arrival times (OTP basis) are kept
    assert (victim.actual_pickup, victim.pickup_arrival) == (first_boarding, first_arrival)
    assert not [e for e in p.ops.exceptions.values() if e.type == "late_pickup" and e.trip_id == victim.id]


def test_fault_before_shift_reassigns_all_of_that_vehicles_shifts():
    from datetime import date

    from roam.config.schema import config_from_dict
    from roam.models import EligibilityStatus, Mode, Rider, TripRequest, TripStatus
    from roam.platform import Platform
    from roam.sim.world import SimWorld

    from .conftest import new_city_config

    day = date(2026, 11, 17)
    p = Platform(today=date(2026, 11, 16))
    p.provision(config_from_dict(new_city_config()))
    p.clock.minute = 600
    scope = p.store.scope("testville")
    pts = [(-75.08, 40.02), (-75.0, 40.08), (-75.06, 40.09), (-74.99, 40.01)]
    for k in range(16):  # spread over both shifts (05:30-14:00 and 14:00-22:00)
        r = scope.add(Rider(id=f"r{k}", tenant_id="testville", eligibility_status=EligibilityStatus.certified))
        p.booking.request_trip("testville", r.id, Mode.paratransit, pts[k % 4], pts[(k + 1) % 4], day, 420 + 45 * k)
    p.clock.today = day
    w = SimWorld(seed=2)
    adapters = p.build_adapters("testville", w)
    for a in adapters.values():
        a.params.no_show_rate = 0.0
    p.start_day("testville", day, adapters)
    d = p.dispatcher("testville", day)
    busiest = max({u.vehicle_id for u in d.units}, key=lambda v: sum(len(u.route) for u in d.units if u.vehicle_id == v))
    adapters[busiest].inject_fault("will not start")  # at 00:00, before any run is active
    w.run_until(26 * 60)
    trips = scope.list(TripRequest)
    assert all(t.status == TripStatus.completed for t in trips), [(t.id, t.status.value) for t in trips]
    assert all(t.vehicle_id != busiest for t in trips)
