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
