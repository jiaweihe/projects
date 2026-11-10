"""Default solver: cheapest feasible insertion + relocate improvement.

Dependency-free and fast enough for city-scale days (hundreds of trips). Used for
real-time insertion in every configuration; used for batch planning unless OR-Tools
is installed and selected.
"""

from __future__ import annotations

from typing import Optional

from ..geo import TravelModel
from .core import Insertion, Solution, Task, Unit, best_insertion, evaluate, remove_task


class InsertionSolver:
    name = "insertion"

    def __init__(self, buffer: float = 1.08, improve_passes: int = 2):
        # buffer > 1 plans with padded travel times so real-world variance does not break windows
        self.buffer = buffer
        self.improve_passes = improve_passes

    def insert(self, units: list[Unit], task: Task, travel: TravelModel) -> Optional[Insertion]:
        ins = best_insertion(units, task, travel, self.buffer)
        if ins is not None:
            ins.unit.route = ins.route
        return ins

    def solve(self, units: list[Unit], tasks: list[Task], travel: TravelModel) -> Solution:
        # hardest first: wheelchair and narrow windows, then by time
        order = sorted(tasks, key=lambda t: (-t.priority, t.pu_earliest, -(t.wc), t.pu_latest - t.pu_earliest))
        unassigned: list[Task] = []
        for t in order:
            if self.insert(units, t, travel) is None:
                unassigned.append(t)
        self._improve(units, travel)
        # retry the unassigned after improvement freed up time
        still: list[Task] = []
        for t in unassigned:
            if self.insert(units, t, travel) is None:
                still.append(t)
        return Solution(units, still)

    def _improve(self, units: list[Unit], travel: TravelModel) -> None:
        for _ in range(self.improve_passes):
            improved = False
            for u in units:
                for tid in list(dict.fromkeys(n.trip_id for n in u.route if n.task is not None)):
                    nodes = [n for n in u.route if n.trip_id == tid]
                    task = nodes[0].task
                    assert task is not None
                    before = evaluate(u, u.route, travel, self.buffer)
                    old_route = list(u.route)
                    remove_task(u, tid)
                    after = evaluate(u, u.route, travel, self.buffer)
                    if before is None or after is None:
                        u.route = old_route
                        continue
                    saving = before.cost - after.cost
                    ins = best_insertion(units, task, travel, self.buffer)
                    if ins is not None and ins.delta < saving - 0.5:
                        ins.unit.route = ins.route
                        improved = True
                    else:
                        u.route = old_route
            if not improved:
                break
