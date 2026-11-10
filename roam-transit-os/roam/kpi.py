"""KPIs built in from day one (spec §9)."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from . import geo
from .costing import Operations, load_cost_model, phase_cost
from .models import Complaint, Incident, Mode, TripRequest, TripStatus

if TYPE_CHECKING:
    from .platform import Platform

KM_PER_MILE = 1.609344


def _pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def compute_kpis(platform: Platform, tenant_id: str, start: date, end: date, cost_model: dict | None = None) -> dict[str, Any]:
    rt = platform.tenant(tenant_id)
    scope = platform.store.scope(tenant_id)
    days = _days(start, end)
    trips = [t for t in scope.list(TripRequest) if start <= t.service_date <= end]
    by = lambda *st: [t for t in trips if t.status in st]  # noqa: E731
    completed = by(TripStatus.completed)
    no_show = by(TripStatus.no_show)
    cancelled = by(TripStatus.cancelled)
    ada_denials = [t for t in by(TripStatus.denied) if t.mode == Mode.paratransit]
    unserved = [t for t in by(TripStatus.denied) if t.mode != Mode.paratransit]
    rejected = by(TripStatus.rejected)

    vrh = rkm = tkm = 0.0
    vehicles: set[str] = set()
    for d in days:
        disp = platform.dispatchers.get((tenant_id, d))
        if disp is None:
            continue
        vrh += disp.revenue_hours()
        rkm += disp.revenue_km()
        tkm += disp.total_km()
        vehicles |= {u.vehicle_id for u in disp.units if any(r.trips_served for k, r in disp.rt.items() if k == u.unit_id)}
    vehicles_in_service = len(vehicles) or len(rt.vehicles)

    # on-time performance: vehicle arrival within the promised window (no-shows included)
    arrivals = [(t.pickup_arrival, t.window) for t in completed + no_show if t.pickup_arrival is not None and t.window]
    on_time = [a for a, w in arrivals if max(a, w[0]) <= w[1] + 1e-6]

    waits: list[float] = []
    for t in completed:
        if t.actual_pickup is None:
            continue
        if t.mode == Mode.paratransit and t.negotiated_pickup is not None:
            waits.append(max(0.0, t.actual_pickup - t.negotiated_pickup))
        elif t.request_made_at is not None:
            waits.append(max(0.0, t.actual_pickup - t.request_made_at))
    ride_times = [t.actual_dropoff - t.actual_pickup for t in completed if t.actual_dropoff and t.actual_pickup]
    passengers = sum(1 + t.companions for t in completed)

    complaints = [c for c in scope.list(Complaint) if start <= c.service_date <= end]
    incidents = scope.list(Incident)
    miles = tkm / KM_PER_MILE

    ops = Operations(
        vehicles=vehicles_in_service,
        revenue_hours=vrh,
        revenue_km=rkm,
        total_km=tkm,
        trips=len(completed),
        service_days=len(days),
        months=len(days) / 30.4,
        wheelchair_trips=sum(1 for t in completed if t.wheelchair),
    )
    cost = phase_cost(rt.config.phase, ops, cost_model or load_cost_model(), rt.config.pricing.model_dump(exclude={"performance"}))

    # phase readiness: share of ride time inside AV operational design domains
    odd_ids = {z for v in rt.vehicles for z in v.odd_zone_ids} | {z.id for z in rt.zones if z.mode == Mode.av_network}
    odd_geoms = [z.geometry for z in rt.zones if z.id in odd_ids]
    inside = total = 0.0
    for t in completed:
        dur = (t.actual_dropoff or 0) - (t.actual_pickup or 0)
        total += dur
        if any(geo.point_in_geometry(t.origin, g) for g in odd_geoms) and any(geo.point_in_geometry(t.destination, g) for g in odd_geoms):
            inside += dur

    seats = [s for s in platform.ops.seats.values() if tenant_id in s.tenant_ids]
    booked = len(trips) - len(rejected)
    return {
        "trips_requested": len(trips),
        "trips_completed": len(completed),
        "passengers": passengers,
        "vehicles_in_service": vehicles_in_service,
        "vehicle_revenue_hours": round(vrh, 2),
        "vehicle_revenue_km": round(rkm, 1),
        "vehicle_total_km": round(tkm, 1),
        "program_cost": round(cost["total"], 2),
        "cost_per_trip": round(cost["cost_per_trip"], 2),
        "cost_per_vrh": round(cost["cost_per_vrh"], 2),
        "roam_take_share": round(cost["roam_take_share"], 4),
        "passengers_per_vrh": round(passengers / vrh, 2) if vrh else 0.0,
        "on_time_performance": round(len(on_time) / len(arrivals), 4) if arrivals else 1.0,
        "wait_avg_min": round(sum(waits) / len(waits), 2) if waits else 0.0,
        "wait_p95_min": round(_pct(waits, 0.95), 2),
        "ride_time_avg_min": round(sum(ride_times) / len(ride_times), 2) if ride_times else 0.0,
        "ada_denials": len(ada_denials),
        "microtransit_unserved": len(unserved),
        "rejected_requests": len(rejected),
        "no_show_rate": round(len(no_show) / (len(completed) + len(no_show)), 4) if completed or no_show else 0.0,
        "cancellation_rate": round(len(cancelled) / booked, 4) if booked else 0.0,
        "complaints_per_1k_trips": round(1000 * len(complaints) / len(completed), 2) if completed else 0.0,
        "incidents_per_100k_miles": round(1e5 * len(incidents) / miles, 2) if miles else 0.0,
        "ops_seats_covering": len(seats),
        "vehicles_per_ops_seat": round(sum(sum(platform.ops.vehicle_counts.get(t, 0) for t in s.tenant_ids) for s in seats) / len(seats), 1)
        if seats
        else 0.0,
        "tenants_per_ops_seat": round(sum(len(s.tenant_ids) for s in seats) / len(seats), 1) if seats else 0.0,
        "phase_readiness_odd_share": round(inside / total, 4) if total else 0.0,
    }
