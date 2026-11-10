"""Routing problem types shared by every solver (spec §7.3).

A *routing unit* is one vehicle on one shift. Constraints modelled:
time windows, ride-time limits, seat + wheelchair capacity, driver shift end and one
meal break, vehicle range, and AV operational design domain (via ``allowed_units``).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..geo import TravelModel
from ..models import LonLat

INF = math.inf


@dataclass
class Task:
    trip_id: str
    pickup: LonLat
    dropoff: LonLat
    pu_earliest: float
    pu_latest: float
    max_ride: float
    seats: int = 1
    wc: int = 0
    pu_service: float = 2.0
    do_service: float = 2.0
    do_latest: float = INF
    allowed_units: set[str] | None = None  # None = any unit
    priority: int = 0  # higher = route first (e.g., ADA paratransit)


@dataclass
class Node:
    kind: Literal["pickup", "dropoff", "break"]
    task: Task | None
    loc: LonLat | None
    earliest: float
    latest: float
    service: float

    @property
    def trip_id(self) -> str | None:
        return self.task.trip_id if self.task else None

    @staticmethod
    def pickup_of(t: Task) -> Node:
        return Node("pickup", t, t.pickup, t.pu_earliest, t.pu_latest, t.pu_service)

    @staticmethod
    def dropoff_of(t: Task) -> Node:
        return Node("dropoff", t, t.dropoff, -INF, t.do_latest, t.do_service)


@dataclass
class Unit:
    """One vehicle-shift. ``start_*`` describe where/when the unit is next free."""

    unit_id: str  # shift id
    vehicle_id: str
    seats: int
    wc: int
    max_range_km: float
    start_loc: LonLat
    start_time: float
    end_loc: LonLat
    end_time: float
    route: list[Node] = field(default_factory=list)
    onboard: dict[str, tuple[Task, float]] = field(default_factory=dict)  # trip_id -> (task, pickup time)
    km_used: float = 0.0
    active: bool = True  # False once faulted / out of service


@dataclass
class Schedule:
    times: list[float]  # service start time per route node
    end_time: float
    drive_min: float
    km: float
    ride_min: float

    @property
    def cost(self) -> float:
        # vehicle minutes dominate; a light weight on rider ride time keeps detours honest
        return self.drive_min + 0.15 * self.ride_min


def evaluate(unit: Unit, nodes: list[Node], travel: TravelModel, buffer: float = 1.0) -> Schedule | None:
    """Return the schedule for ``nodes`` on ``unit`` or None if any constraint is violated."""
    return evaluate_at(unit, nodes, travel, buffer)[0]


def evaluate_at(unit: Unit, nodes: list[Node], travel: TravelModel, buffer: float = 1.0) -> tuple[Schedule | None, int]:
    """Like :func:`evaluate`, plus the index of the first violating node
    (``len(nodes)`` when the violation is the return to depot / range)."""
    t = unit.start_time
    loc = unit.start_loc
    seats = sum(task.seats for task, _ in unit.onboard.values())
    wc = sum(task.wc for task, _ in unit.onboard.values())
    pu_time = {tid: pt for tid, (_, pt) in unit.onboard.items()}
    km = unit.km_used
    drive = 0.0
    ride = 0.0
    times: list[float] = []
    for idx, n in enumerate(nodes):
        if n.loc is not None and n.loc != loc:
            tt = travel.travel_min(loc, n.loc) * buffer
            km += travel.distance_km(loc, n.loc)
            drive += tt
            t += tt
            loc = n.loc
        start = max(t, n.earliest)
        if start > n.latest + 1e-9:
            return None, idx
        if n.kind == "pickup":
            assert n.task is not None
            seats += n.task.seats
            wc += n.task.wc
            if seats > unit.seats or wc > unit.wc:
                return None, idx
            pu_time[n.task.trip_id] = start
        elif n.kind == "dropoff":
            assert n.task is not None
            p = pu_time.get(n.task.trip_id)
            if p is None:
                return None, idx  # dropoff before pickup
            r = start - p
            if r > n.task.max_ride + 1e-9:
                return None, idx
            ride += r
            seats -= n.task.seats
            wc -= n.task.wc
        times.append(start)
        t = start + n.service
    if loc != unit.end_loc:
        tt = travel.travel_min(loc, unit.end_loc) * buffer
        km += travel.distance_km(loc, unit.end_loc)
        drive += tt
        t += tt
    if t > unit.end_time + 1e-9 or km > unit.max_range_km + 1e-9:
        return None, len(nodes)
    return Schedule(times, t, drive, km, ride), -1


@dataclass
class Insertion:
    unit: Unit
    i: int  # pickup index in the new route
    j: int  # dropoff index in the new route
    delta: float
    schedule: Schedule
    route: list[Node]


def best_insertion(units: Iterable[Unit], task: Task, travel: TravelModel, buffer: float = 1.0) -> Insertion | None:
    best: Insertion | None = None
    pu, do = Node.pickup_of(task), Node.dropoff_of(task)
    for u in units:
        if not u.active or (task.allowed_units is not None and u.unit_id not in task.allowed_units):
            continue
        if task.seats > u.seats or task.wc > u.wc:
            continue
        if task.pu_latest < u.start_time or task.pu_earliest > u.end_time:
            continue
        base = evaluate(u, u.route, travel, buffer)
        if base is None:
            continue
        r = u.route
        n = len(r)
        for i in range(n + 1):
            # cheap prune: nodes before i that must start after the pickup's latest time make i too late
            # the prefix before i is unchanged, so a pickup after node i-1 cannot start earlier than it
            if i > 0 and base.times[i - 1] > task.pu_latest:
                break
            for j in range(i, n + 1):
                cand = r[:i] + [pu] + r[i:j] + [do] + r[j:]
                s, fail = evaluate_at(u, cand, travel, buffer)
                if s is None:
                    if fail <= j + 1:
                        # violation at or before the drop-off: every later drop-off position
                        # shares that prefix (or a later drop-off), so it fails too
                        break
                    continue
                d = s.cost - base.cost
                if best is None or d < best.delta:
                    best = Insertion(u, i, j + 1, d, s, cand)
    return best


def remove_task(unit: Unit, trip_id: str) -> None:
    unit.route = [n for n in unit.route if n.trip_id != trip_id]


@dataclass
class Solution:
    units: list[Unit]
    unassigned: list[Task]


class Solver(Protocol):
    """Swappable solver (OR-Tools, VROOM, heuristic). Must not mutate ``units`` it rejects."""

    name: str

    def solve(self, units: list[Unit], tasks: list[Task], travel: TravelModel) -> Solution: ...

    def insert(self, units: list[Unit], task: Task, travel: TravelModel) -> Insertion | None: ...


def make_break(earliest: float, latest: float, duration: float) -> Node:
    return Node("break", None, None, earliest, latest, duration)
