import pytest

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


def test_ortools_solver_if_available():
    pytest.importorskip("ortools")
    from roam.dispatch.ortools_solver import ORToolsSolver

    units = [unit("u1"), unit("u2")]
    tasks = [task(f"t{i}", 420 + 30 * i) for i in range(10)]
    sol = ORToolsSolver(time_limit_s=2).solve(units, tasks, TRAVEL)
    assert not sol.unassigned
    for u in sol.units:
        assert evaluate(u, u.route, TRAVEL, 1.10) is not None


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
