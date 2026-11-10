"""Per-tenant, per-service-day dispatcher.

Lifecycle:
1. *Booking*: paratransit bookings are inserted into the tentative day plan, so every
   accepted trip already has a feasible slot (this is how capacity denials are avoided
   or, if unavoidable, detected and alerted at booking time).
2. *Batch*: before the day starts the whole day is re-optimised with the batch solver
   (any ``Solver``); the tentative plan is kept if the batch result is worse.
3. *Live*: runs are pushed to vehicle adapters; adapter events keep the plan in sync and
   real-time requests are inserted into what is left of each run.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from ..adapters.base import RunPatch, VehicleAdapter, VehicleEvent
from ..models import LonLat, Run, Shift, Stop, StopType
from .core import Insertion, Node, Solver, Task, Unit, best_insertion, evaluate, make_break

ExceptionSink = Callable[..., None]


@dataclass
class UnitRuntime:
    run: Run
    first_revenue: float | None = None
    last_revenue: float | None = None
    revenue_km_start: float | None = None
    odometer: float = 0.0
    revenue_km: float = 0.0
    committed: Node | None = None
    trips_served: set[str] = field(default_factory=set)


class Dispatcher:
    def __init__(
        self,
        tenant_id: str,
        service_date: date,
        shifts: list[Shift],
        vehicles: dict,
        solver: Solver,
        travel,
        batch_solver: Solver | None = None,
        on_exception: ExceptionSink | None = None,
        on_vehicle_event: Callable[[VehicleEvent], None] | None = None,
    ):
        self.tenant_id = tenant_id
        self.service_date = service_date
        self.solver = solver
        self.batch_solver = batch_solver or solver
        self.travel = travel
        self.on_exception = on_exception or (lambda **kw: None)
        self.on_vehicle_event = on_vehicle_event or (lambda e: None)
        self.units: list[Unit] = []
        self.rt: dict[str, UnitRuntime] = {}
        self.tasks: dict[str, Task] = {}
        self.adapters: dict[str, VehicleAdapter] = {}
        self.live = False
        for sh in shifts:
            v = vehicles[sh.vehicle_id]
            u = Unit(
                unit_id=sh.id,
                vehicle_id=v.id,
                seats=v.seats,
                wc=v.wheelchair_positions,
                max_range_km=v.max_range_km,
                start_loc=sh.depot,
                start_time=sh.start,
                end_loc=sh.depot,
                end_time=sh.end,
            )
            if sh.break_after_min is not None and sh.end - sh.start > sh.break_after_min + 60:
                b0 = sh.start + sh.break_after_min - 60
                u.route.append(make_break(b0, b0 + 120, sh.break_duration_min))
            self.units.append(u)
            self.rt[u.unit_id] = UnitRuntime(
                run=Run(id=f"run:{sh.id}", tenant_id=tenant_id, shift_id=sh.id, vehicle_id=v.id, shift_start=sh.start, shift_end=sh.end)
            )

    # ------------------------------------------------------------- planning
    def unit(self, unit_id: str) -> Unit:
        return next(u for u in self.units if u.unit_id == unit_id)

    def allowed_units_for(self, vehicle_ids: set[str] | None) -> set[str] | None:
        if vehicle_ids is None:
            return None
        return {u.unit_id for u in self.units if u.vehicle_id in vehicle_ids}

    def try_insert(self, task: Task, now: float | None = None) -> Insertion | None:
        if now is not None:
            for u in self.units:
                u.start_time = max(u.start_time, now)
        ins = self.solver.insert(self.units, task, self.travel)
        if ins is None:
            return None
        self.tasks[task.trip_id] = task
        if self.live:
            self._push(ins.unit)
        return ins

    def repair_insert(self, task: Task) -> bool:
        """Repair step before any denial (ejection chain of depth 1): move one already-promised
        trip to another vehicle so the new trip fits. Every existing promise is kept, because
        moved trips keep their windows and are only accepted where feasible."""
        buf = getattr(self.solver, "buffer", 1.0)
        candidates = [u for u in self.units if u.active and (task.allowed_units is None or u.unit_id in task.allowed_units)]
        candidates = [u for u in candidates if u.start_time <= task.pu_latest and u.end_time >= task.pu_earliest]
        for u in candidates:
            movable = [n.task for n in u.route if n.kind == "pickup" and n.task is not None]
            # try trips closest in time to the new one first
            movable.sort(key=lambda t: abs(t.pu_earliest - task.pu_earliest))
            for x in movable[:6]:
                saved = list(u.route)
                u.route = [n for n in u.route if n.trip_id != x.trip_id]
                ins = best_insertion([u], task, self.travel, buf)
                if ins is not None:
                    u.route = ins.route
                    others = [v for v in self.units if v is not u]
                    ins_x = best_insertion(others, x, self.travel, buf)
                    if ins_x is not None:
                        ins_x.unit.route = ins_x.route
                        self.tasks[task.trip_id] = task
                        if self.live:
                            self._push(u)
                            self._push(ins_x.unit)
                        return True
                u.route = saved
        return False

    def planned_pickup(self, trip_id: str) -> float | None:
        for u in self.units:
            s = evaluate(u, u.route, self.travel, getattr(self.solver, "buffer", 1.0))
            if s is None:
                continue
            for n, t in zip(u.route, s.times, strict=True):
                if n.kind == "pickup" and n.trip_id == trip_id:
                    return t
        return None

    def remove_trip(self, trip_id: str) -> bool:
        """Drop a trip from the plan, including one the vehicle is already driving to."""
        self.tasks.pop(trip_id, None)
        for u in self.units:
            if trip_id in u.onboard or any(n.trip_id == trip_id for n in u.route):
                u.onboard.pop(trip_id, None)
                u.route = [n for n in u.route if n.trip_id != trip_id]
                if self.live:
                    adapter = self.adapters[u.vehicle_id]
                    for sid in (f"{trip_id}:pu", f"{trip_id}:do"):
                        adapter.cancel_stop(sid, "trip cancelled")
                    self._push(u)
                return True
        return False

    def batch_optimize(self) -> dict:
        """Re-plan the whole day from scratch; keep the tentative plan unless batch is at least as good."""
        buf = getattr(self.solver, "buffer", 1.0)
        tentative = copy.deepcopy(self.units)
        tentative_cost = sum((evaluate(u, u.route, self.travel, buf) or _Huge).cost for u in tentative)
        fresh = copy.deepcopy(self.units)
        for u in fresh:
            u.route = [n for n in u.route if n.kind == "break"]
        sol = self.batch_solver.solve(fresh, list(self.tasks.values()), self.travel)
        batch_cost = sum((evaluate(u, u.route, self.travel, buf) or _Huge).cost for u in sol.units)
        used = "tentative"
        if not sol.unassigned and batch_cost <= tentative_cost:
            self.units = sol.units
            used = self.batch_solver.name
        else:
            self.units = tentative
        return {
            "solver": used,
            "tentative_cost": round(tentative_cost, 1),
            "batch_cost": round(batch_cost, 1),
            "batch_unassigned": len(sol.unassigned),
        }

    # ------------------------------------------------------------------ live
    def go_live(self, adapters: dict[str, VehicleAdapter]) -> None:
        self.adapters = adapters
        self.live = True
        for a in adapters.values():
            a.on_event(self._handle_event)
        for u in sorted(self.units, key=lambda u: u.start_time):
            run = self._build_run(u)
            r = self.rt[u.unit_id]
            r.run = run
            run.status = "assigned"
            self.adapters[u.vehicle_id].assign_run(run)

    def _stop_id(self, u: Unit, n: Node, k: int) -> str:
        if n.kind == "break":
            return f"{u.unit_id}:break:{int(n.earliest)}"
        return f"{n.trip_id}:{'pu' if n.kind == 'pickup' else 'do'}"

    def _build_run(self, u: Unit) -> Run:
        sched = evaluate(u, u.route, self.travel, getattr(self.solver, "buffer", 1.0))
        run = self.rt[u.unit_id].run
        stops = []
        for k, n in enumerate(u.route):
            stops.append(
                Stop(
                    id=self._stop_id(u, n, k),
                    run_id=run.id,
                    trip_request_id=n.trip_id,
                    type=StopType.break_ if n.kind == "break" else StopType(n.kind),
                    location=n.loc,
                    earliest=n.earliest if n.earliest > -1e9 else 0.0,
                    latest=n.latest if n.latest < 1e9 else 48 * 60,
                    service_min=n.service,
                    eta=sched.times[k] if sched else None,
                )
            )
        run.stops = stops
        return run

    def _push(self, u: Unit) -> None:
        run = self._build_run(u)
        self.adapters[u.vehicle_id].update_run(run.id, RunPatch(add_stops=run.stops))

    def _unit_by_run(self, run_id: str) -> Unit:
        for u in self.units:
            if self.rt[u.unit_id].run.id == run_id:
                return u
        raise KeyError(run_id)

    def _handle_event(self, e: VehicleEvent) -> None:
        if e.type == "fault":  # may arrive between runs (no run_id): handle by vehicle
            self._handle_fault(e.vehicle_id, e)
            self.on_vehicle_event(e)
            return
        run_id = e.payload.get("run_id")
        if run_id is None:
            self.on_vehicle_event(e)
            return
        u = self._unit_by_run(run_id)
        r = self.rt[u.unit_id]
        if "odometer" in e.payload:
            r.odometer = e.payload["odometer"]
        if e.type == "en_route":
            idx = next((i for i, n in enumerate(u.route) if self._stop_id(u, n, i) == e.stop_id), None)
            if idx is None:
                return
            n = u.route.pop(idx)
            r.committed = n
            eta = e.payload.get("eta", e.timestamp)
            if n.loc is not None:
                u.start_loc = n.loc
            u.start_time = max(eta, n.earliest) + n.service
            if n.kind == "pickup" and n.task is not None:
                u.onboard[n.task.trip_id] = (n.task, max(eta, n.earliest))
            elif n.kind == "dropoff" and n.task is not None:
                u.onboard.pop(n.task.trip_id, None)
            late_by = max(eta, n.earliest) - n.latest
            if n.kind == "pickup" and late_by > 0:
                self.on_exception(
                    type="predicted_late_pickup",
                    severity=3,
                    tenant_id=self.tenant_id,
                    vehicle_id=u.vehicle_id,
                    trip_id=n.trip_id,
                    at=e.timestamp,
                    message=f"pickup predicted {late_by:.0f} min past planning window",
                )
        elif e.type in ("arrival", "boarding", "dropoff"):
            if r.first_revenue is None and e.type == "boarding":
                r.first_revenue = e.timestamp
                r.revenue_km_start = r.odometer
            if e.type == "dropoff":
                r.last_revenue = e.timestamp
                if r.revenue_km_start is not None:
                    r.revenue_km = r.odometer - r.revenue_km_start
                if e.trip_id:
                    r.trips_served.add(e.trip_id)
            if r.committed is not None and e.type in ("boarding", "dropoff"):
                u.start_time = max(u.start_time, e.timestamp + r.committed.service)
        elif e.type == "no_show":
            if e.trip_id:
                u.onboard.pop(e.trip_id, None)
                self.tasks.pop(e.trip_id, None)
                u.route = [n for n in u.route if n.trip_id != e.trip_id]
                u.start_time = e.timestamp
                self._push(u)
        self.on_vehicle_event(e)

    def _handle_fault(self, vehicle_id: str, e: VehicleEvent) -> None:
        """Take every shift of the broken vehicle out of service, re-plan its pickups on other
        vehicles and send a rescue for anyone onboard."""
        mine = [x for x in self.units if x.vehicle_id == vehicle_id]
        stranded: list[tuple[Task, LonLat]] = []
        pending: list[Task] = []
        for u in mine:
            u.active = False
            stranded += [(task, e.location or u.start_loc) for task, _ in u.onboard.values()]
            pending += [n.task for n in u.route if n.kind == "pickup" and n.task is not None]
            u.onboard.clear()
            u.route = []
        self.on_exception(
            type="vehicle_fault",
            severity=1 if stranded else 2,
            tenant_id=self.tenant_id,
            vehicle_id=vehicle_id,
            at=e.timestamp,
            message=f"vehicle fault; {len(stranded)} riders onboard, {len(pending)} pickups to reassign",
        )
        for t in pending:
            t2 = copy.copy(t)
            t2.pu_latest = max(t2.pu_latest, e.timestamp + 45)
            if self.try_insert(t2, now=e.timestamp) is None:
                self.on_exception(
                    type="reassign_failed",
                    severity=2,
                    tenant_id=self.tenant_id,
                    trip_id=t.trip_id,
                    at=e.timestamp,
                    message="could not reassign trip after vehicle fault; arrange backup",
                )
        for task, where in stranded:
            rescue = copy.copy(task)
            rescue.pickup, rescue.pu_earliest, rescue.pu_latest = where, e.timestamp, e.timestamp + 45
            rescue.allowed_units, rescue.priority = None, 10
            if self.try_insert(rescue, now=e.timestamp) is None:
                self.on_exception(
                    type="rescue_failed",
                    severity=1,
                    tenant_id=self.tenant_id,
                    trip_id=task.trip_id,
                    at=e.timestamp,
                    message="stranded rider: no rescue vehicle available",
                )

    # -------------------------------------------------------------- metrics
    def revenue_hours(self) -> float:
        return sum((r.last_revenue - r.first_revenue) / 60 for r in self.rt.values() if r.first_revenue and r.last_revenue)

    def revenue_km(self) -> float:
        return sum(r.revenue_km for r in self.rt.values())

    def total_km(self) -> float:
        return sum(r.odometer for r in self.rt.values())


class _HugeCost:
    cost = 1e12


_Huge = _HugeCost()
