"""Platform: wires tenants, store, dispatchers, adapters, booking and the ops center."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any

from .adapters.av_partner import AVPartnerAdapter, SimulatedAVProvider
from .adapters.base import AssistContext, AssistTicket, Telemetry, VehicleAdapter, VehicleEvent
from .adapters.human_driver import HumanDriverAdapter
from .adapters.simulator import SimParams, SimulatorAdapter
from .booking import BookingService
from .config.schema import TenantConfig, load_config
from .config.validate import ValidationReport, validate
from .dispatch.core import Solver
from .dispatch.dispatcher import Dispatcher
from .dispatch.insertion import InsertionSolver
from .models import AdapterKind, Event, TripRequest, TripStatus, new_id
from .ops.console import OpsCenter, ops_sink
from .ops.incidents import LogNotifier
from .sim.world import SimWorld
from .store import Store
from .tenancy import TenantRuntime, build_runtime


@dataclass
class Clock:
    today: date
    minute: float = 0.0


class ProvisioningError(ValueError):
    def __init__(self, report: ValidationReport):
        super().__init__("; ".join(report.errors))
        self.report = report


class Platform:
    def __init__(self, today: date | None = None, batch_solver: Solver | None = None):
        self.store = Store()
        self.ops = OpsCenter()
        self.notifier = LogNotifier()
        self.clock = Clock(today or date.today())
        self.booking = BookingService(self)
        self.solver = InsertionSolver()
        self.batch_solver = batch_solver or self.solver  # any Solver (OR-Tools/VROOM wrappers plug in here)
        self.dispatchers: dict[tuple[str, date], Dispatcher] = {}
        self.adapters: dict[str, VehicleAdapter] = {}
        self.telemetry: dict[str, Telemetry] = {}  # last known position per vehicle

    # ---------------------------------------------------------- tenancy
    def provision(self, source: str | Path | tuple[TenantConfig, dict], *, require_go_live: bool = False) -> TenantRuntime:
        cfg, geoms = load_config(source) if not isinstance(source, tuple) else source
        report = validate(cfg, geoms)
        if not report.ok or (require_go_live and not report.can_go_live):
            raise ProvisioningError(report if report.errors else ValidationReport(errors=report.golive_blockers))
        rt = build_runtime(cfg, geoms, report)
        if cfg.gtfs_feed and not isinstance(source, tuple):
            from .exports.gtfs_import import load_stops

            rt.gtfs_stops = load_stops(Path(source).parent / cfg.gtfs_feed)
        self.store.tenants[cfg.id] = rt
        scope = self.store.scope(cfg.id)
        for rec in [rt.tenant, rt.policy, *rt.zones, *rt.vehicles, *rt.funding]:
            scope.add(rec)
        self.ops.register_tenant(cfg.id, len(rt.vehicles))
        return rt

    def tenant(self, tenant_id: str) -> TenantRuntime:
        return self.store.tenants[tenant_id]

    # ------------------------------------------------------- dispatching
    def dispatcher(self, tenant_id: str, service_date: date) -> Dispatcher:
        key = (tenant_id, service_date)
        if key not in self.dispatchers:
            rt = self.tenant(tenant_id)
            d = Dispatcher(
                tenant_id,
                service_date,
                rt.shifts_for(service_date),
                {v.id: v for v in rt.vehicles},
                self.solver,
                rt.travel,
                batch_solver=self.batch_solver,
                on_exception=ops_sink(self.ops, service_date),
                on_vehicle_event=partial(self._on_vehicle_event, tenant_id, service_date),
            )
            self.dispatchers[key] = d
        return self.dispatchers[key]

    def build_adapters(
        self, tenant_id: str, world: SimWorld | None = None, sim_params: SimParams | None = None
    ) -> dict[str, VehicleAdapter]:
        """Create one adapter per vehicle. With a ``world`` every vehicle is simulated
        (human-driven vehicles run as simulator adapters; AVs via the simulated provider)."""
        rt = self.tenant(tenant_id)
        out: dict[str, VehicleAdapter] = {}
        zone_geo = {z.id: z.geometry for z in rt.zones}
        for v in rt.vehicles:
            caps = v.capabilities()
            if world is not None:
                sim = SimulatorAdapter(
                    v.id,
                    caps,
                    world,
                    rt.travel,
                    rt.config.depot,
                    sim_params,
                    rng=__import__("random").Random(f"{v.id}:{world.rng.random()}"),
                )
                if v.adapter_kind == AdapterKind.av_partner:
                    a: VehicleAdapter = AVPartnerAdapter(
                        v.id,
                        caps,
                        SimulatedAVProvider({v.id: sim}),
                        {z: zone_geo[z] for z in v.odd_zone_ids},
                        on_assist=partial(self._on_assist, tenant_id),
                    )
                else:
                    a = sim
            elif v.adapter_kind == AdapterKind.human_driver:
                a = HumanDriverAdapter(v.id, caps)
            else:
                raise NotImplementedError(f"live {v.adapter_kind.value} adapter requires a provider client (VERIFY)")
            a.on_telemetry(self._on_telemetry)
            out[v.id] = a
            self.adapters[v.id] = a
        return out

    def start_day(self, tenant_id: str, service_date: date, adapters: dict[str, VehicleAdapter], optimize: bool = True) -> dict[str, Any]:
        d = self.dispatcher(tenant_id, service_date)
        info = d.batch_optimize() if optimize and d.tasks else {"solver": "none"}
        for tid in d.tasks:
            trip = self.store.scope(tenant_id).get(TripRequest, tid)
            if trip.status == TripStatus.booked:
                trip.status = TripStatus.scheduled
        d.go_live(adapters)
        return info

    # ------------------------------------------------------- event intake
    def _on_telemetry(self, t: Telemetry) -> None:
        self.telemetry[t.vehicle_id] = t

    def _on_assist(self, tenant_id: str, ctx: AssistContext, ticket: AssistTicket) -> None:
        self.ops.raise_exception(
            type="remote_assist",
            severity=2,
            tenant_id=tenant_id,
            at=ctx.timestamp,
            vehicle_id=ctx.vehicle_id,
            service_date=self.clock.today,
            message=f"AV remote assist: {ctx.reason}",
            ticket_id=ticket.ticket_id,
        )

    def _on_vehicle_event(self, tenant_id: str, service_date: date, e: VehicleEvent) -> None:
        scope = self.store.scope(tenant_id)
        if e.type != "en_route":
            scope.add(
                Event(
                    id=new_id("evt"),
                    tenant_id=tenant_id,
                    vehicle_id=e.vehicle_id,
                    type=e.type,
                    timestamp=e.timestamp,
                    service_date=service_date,
                    location=e.location,
                    payload={k: v for k, v in e.payload.items() if k != "eta"} | {"trip_id": e.trip_id, "stop_id": e.stop_id},
                )
            )
        if not e.trip_id:
            return
        try:
            trip = scope.get(TripRequest, e.trip_id)
        except KeyError:
            return
        if trip.status == TripStatus.cancelled:
            return  # late vehicle events never resurrect a cancelled trip
        is_pickup = (e.stop_id or "").endswith(":pu")
        if e.type == "en_route" and is_pickup:
            trip.status, trip.vehicle_id = TripStatus.en_route, e.vehicle_id
        elif e.type == "arrival" and is_pickup:
            trip.pickup_arrival = e.timestamp
            if trip.window and max(e.timestamp, trip.window[0]) > trip.window[1]:
                self.ops.raise_exception(
                    type="late_pickup",
                    severity=3,
                    tenant_id=tenant_id,
                    at=e.timestamp,
                    vehicle_id=e.vehicle_id,
                    trip_id=trip.id,
                    service_date=service_date,
                    message=f"pickup {e.timestamp - trip.window[1]:.0f} min outside window",
                )
        elif e.type == "boarding":
            trip.status, trip.actual_pickup, trip.vehicle_id = TripStatus.onboard, e.timestamp, e.vehicle_id
        elif e.type == "dropoff":
            trip.status, trip.actual_dropoff = TripStatus.completed, e.timestamp
        elif e.type == "no_show":
            trip.status = TripStatus.no_show
            self.ops.raise_exception(
                type="no_show",
                severity=4,
                tenant_id=tenant_id,
                at=e.timestamp,
                vehicle_id=e.vehicle_id,
                trip_id=trip.id,
                service_date=service_date,
                message="rider no-show",
            )
