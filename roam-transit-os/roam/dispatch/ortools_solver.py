"""Google OR-Tools batch solver (pickup-and-delivery with time windows).

Optional: requires ``pip install ortools``. Real-time insertion is delegated to the
insertion heuristic, which works against the OR-Tools plan.
"""

from __future__ import annotations

import math
from typing import Optional

from ..geo import TravelModel
from .core import INF, Insertion, Node, Solution, Task, Unit, evaluate
from .insertion import InsertionSolver

SCALE = 10  # tenths of a minute
BIG = 10**7


class ORToolsSolver:
    name = "ortools"

    def __init__(self, time_limit_s: int = 10, buffer: float = 1.10):
        from ortools.constraint_solver import pywrapcp  # noqa: F401  (fail fast if missing)

        self.time_limit_s = time_limit_s
        self.buffer = buffer
        self.dropped_breaks: list[str] = []
        self._fallback = InsertionSolver(buffer=buffer)

    def insert(self, units: list[Unit], task: Task, travel: TravelModel) -> Optional[Insertion]:
        return self._fallback.insert(units, task, travel)

    def solve(self, units: list[Unit], tasks: list[Task], travel: TravelModel) -> Solution:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2

        if not tasks:
            return Solution(units, [])
        # batch solver plans from empty units; fold any tasks already on routes back in
        existing = {n.task.trip_id: n.task for u in units for n in u.route if n.task is not None}
        if existing:
            tasks = list({**existing, **{t.trip_id: t for t in tasks}}.values())
        # node layout: [unit starts][unit ends][pickups][dropoffs]
        V = len(units)
        locs: list = [u.start_loc for u in units] + [u.end_loc for u in units]
        tw: list[tuple[float, float]] = [(u.start_time, u.end_time) for u in units] * 2
        service = [0.0] * (2 * V)
        seats_d = [0] * (2 * V)
        wc_d = [0] * (2 * V)
        pairs = []
        for t in tasks:
            pi = len(locs)
            locs.append(t.pickup)
            tw.append((t.pu_earliest, t.pu_latest))
            service.append(t.pu_service)
            seats_d.append(t.seats)
            wc_d.append(t.wc)
            di = len(locs)
            locs.append(t.dropoff)
            tw.append((0.0, t.do_latest if t.do_latest < INF else 48 * 60))
            service.append(t.do_service)
            seats_d.append(-t.seats)
            wc_d.append(-t.wc)
            pairs.append((t, pi, di))
        N = len(locs)
        mat = [[0] * N for _ in range(N)]
        for a in range(N):
            for b in range(N):
                if a != b:
                    mat[a][b] = math.ceil(travel.travel_min(locs[a], locs[b]) * self.buffer * SCALE)

        mgr = pywrapcp.RoutingIndexManager(N, V, list(range(V)), list(range(V, 2 * V)))
        routing = pywrapcp.RoutingModel(mgr)

        def transit(i, j):
            a, b = mgr.IndexToNode(i), mgr.IndexToNode(j)
            return mat[a][b] + math.ceil(service[a] * SCALE)

        cb = routing.RegisterTransitCallback(transit)
        routing.SetArcCostEvaluatorOfAllVehicles(cb)
        horizon = 48 * 60 * SCALE
        routing.AddDimension(cb, horizon, horizon, False, "Time")
        time = routing.GetDimensionOrDie("Time")
        for node in range(N):
            if node < 2 * V:
                continue
            lo, hi = tw[node]
            time.CumulVar(mgr.NodeToIndex(node)).SetRange(int(lo * SCALE), int(hi * SCALE))
        for v, u in enumerate(units):
            time.CumulVar(routing.Start(v)).SetRange(int(u.start_time * SCALE), int(u.start_time * SCALE))
            time.CumulVar(routing.End(v)).SetRange(int(u.start_time * SCALE), int(u.end_time * SCALE))

        for name, dem, caps in (("Seats", seats_d, [u.seats for u in units]), ("WC", wc_d, [u.wc for u in units])):
            dcb = routing.RegisterUnaryTransitCallback(lambda i, d=dem: d[mgr.IndexToNode(i)])
            routing.AddDimensionWithVehicleCapacity(dcb, 0, caps, True, name)

        solver = routing.solver()
        unit_index = {u.unit_id: v for v, u in enumerate(units)}
        for t, pi, di in pairs:
            p, d = mgr.NodeToIndex(pi), mgr.NodeToIndex(di)
            routing.AddPickupAndDelivery(p, d)
            solver.Add(routing.VehicleVar(p) == routing.VehicleVar(d))
            solver.Add(time.CumulVar(p) <= time.CumulVar(d))
            solver.Add(time.CumulVar(d) - time.CumulVar(p) <= int(t.max_ride * SCALE))
            routing.AddDisjunction([p, d], BIG, 2)  # droppable, at a very high penalty
            if t.allowed_units is not None:
                allowed = [unit_index[x] for x in t.allowed_units if x in unit_index]
                routing.VehicleVar(p).SetValues([-1] + allowed)

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        params.time_limit.seconds = self.time_limit_s
        sol = routing.SolveWithParameters(params)
        if sol is None:
            return self._fallback.solve(units, tasks, travel)

        by_node = {}
        for t, pi, di in pairs:
            by_node[pi] = Node.pickup_of(t)
            by_node[di] = Node.dropoff_of(t)
        assigned: set[str] = set()
        for v, u in enumerate(units):
            breaks = [n for n in u.route if n.kind == "break"]
            route: list[Node] = []
            idx = sol.Value(routing.NextVar(routing.Start(v)))
            while not routing.IsEnd(idx):
                n = by_node[mgr.IndexToNode(idx)]
                route.append(n)
                assigned.add(n.trip_id)  # type: ignore[arg-type]
                idx = sol.Value(routing.NextVar(idx))
            # place the driver break at its best feasible slot (OR-Tools model above omits it)
            for b in breaks:
                best = None
                for k in range(len(route) + 1):
                    cand = route[:k] + [b] + route[k:]
                    s = evaluate(u, cand, travel, self.buffer)
                    if s is not None and (best is None or s.cost < best[0]):
                        best = (s.cost, cand)
                route = best[1] if best else route + [b]
            u.route = route
        unassigned = [t for t, _, _ in pairs if t.trip_id not in assigned]
        # OR-Tools may delay a pickup inside its window to respect ride time; our executable
        # model starts service as early as possible. Repair any route that does not verify.
        bumped: list[Task] = []
        for u in units:
            while u.route and evaluate(u, u.route, travel, self.buffer) is None:
                k = next(i for i in range(1, len(u.route) + 1) if evaluate(u, u.route[:i], travel, self.buffer) is None)
                bad = u.route[k - 1]
                if bad.task is None:  # driver break: move it to the best slot that verifies
                    u.route = [n for n in u.route if n is not bad]
                    slots = [u.route[:i] + [bad] + u.route[i:] for i in range(len(u.route) + 1)]
                    ok = [r for r in slots if evaluate(u, r, travel, self.buffer) is not None]
                    if ok:
                        u.route = ok[0]
                    else:
                        self.dropped_breaks.append(u.unit_id)  # surfaced to ops by the dispatcher caller
                    continue
                bumped.append(bad.task)
                u.route = [n for n in u.route if n.trip_id != bad.trip_id]
        for t in bumped:
            if self._fallback.insert(units, t, travel) is None:
                unassigned.append(t)
        return Solution(units, unassigned)
