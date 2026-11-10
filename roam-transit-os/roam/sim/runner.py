"""Simulate one service day for one or more tenants in a shared world.

Paratransit trips are booked the day before through the real booking service (so
negotiation and denial logic run), the day is batch-optimised, then simulated vehicles
execute it while real-time microtransit requests arrive.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ..adapters.simulator import SimParams
from ..models import Channel, Complaint, TripRequest, TripStatus, new_id
from ..platform import Platform
from .demand import Demand, DemandSpec, generate
from .world import SimWorld


@dataclass
class DayResult:
    service_date: date
    tenants: dict[str, dict[str, Any]] = field(default_factory=dict)  # tenant_id -> KPIs
    batch: dict[str, Any] = field(default_factory=dict)
    demand: dict[str, Demand] = field(default_factory=dict)


def simulate_day(
    platform: Platform,
    service_date: date,
    specs: dict[str, DemandSpec],
    sim_params: SimParams | None = None,
    seed: int = 11,
    complaint_rate_late: float = 0.15,
) -> DayResult:
    from ..kpi import compute_kpis

    res = DayResult(service_date)
    rng = random.Random(seed)
    # ---------------------------------------------------- day before: bookings
    platform.clock.today = service_date - timedelta(days=1)
    for tid, spec in specs.items():
        rt = platform.tenant(tid)
        demand = generate(rt, service_date, spec, seed)
        res.demand[tid] = demand
        scope = platform.store.scope(tid)
        for r in demand.riders:
            scope.add(r)
        advance = [d for d in demand.items if d.request_at is None]
        rng.shuffle(advance)
        for k, d in enumerate(advance):
            platform.clock.minute = 9 * 60 + (7.5 * 60) * k / max(1, len(advance))  # 09:00-16:30
            channel = rng.choices([Channel.ivr, Channel.app, Channel.web, Channel.agent], [0.45, 0.25, 0.15, 0.15])[0]
            platform.booking.request_trip(tid, d.rider_id, d.mode, d.origin, d.destination, service_date, d.time, channel, d.time_type)  # type: ignore[arg-type]

    # ---------------------------------------------------- service day
    platform.clock.today = service_date
    platform.clock.minute = 0
    world = SimWorld(seed=seed)
    for tid in specs:
        adapters = platform.build_adapters(tid, world, sim_params)
        res.batch[tid] = platform.start_day(tid, service_date, adapters)
        for d in res.demand[tid].items:
            if d.request_at is None:
                continue

            def make(d=d, tid=tid):
                def fire() -> None:
                    platform.clock.minute = world.now
                    platform.booking.request_trip(tid, d.rider_id, d.mode, d.origin, d.destination, service_date, world.now, Channel.app)

                return fire

            world.schedule(d.request_at, make())
    world.run_until(26 * 60)
    platform.clock.minute = 26 * 60

    # ---------------------------------------------------- complaints (synthetic)
    for tid in specs:
        scope = platform.store.scope(tid)
        for t in scope.list(TripRequest, service_date=service_date):
            late = t.window and t.pickup_arrival and t.pickup_arrival > t.window[1]
            p = complaint_rate_late if late else 0.002
            if t.status in (TripStatus.completed, TripStatus.no_show) and rng.random() < p:
                scope.add(
                    Complaint(
                        id=new_id("cmp"),
                        tenant_id=tid,
                        service_date=service_date,
                        trip_request_id=t.id,
                        category="late" if late else "service",
                    )
                )
        res.tenants[tid] = compute_kpis(platform, tid, service_date, service_date)
    return res
