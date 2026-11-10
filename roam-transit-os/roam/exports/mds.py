"""Mobility Data Specification feed (spec §3, §7.7): Roam reports into the city / regulator
and Autonomy OS like any other operator.

Shapes follow MDS 2.x conventions for the ``passenger-services`` mode (vehicles, events,
trips). **VERIFY** field names and the event vocabulary against the MDS version the city
or Autonomy OS requires, and run the official schema validator before go-live.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..models import AdapterKind, Event, TripRequest, TripStatus

if TYPE_CHECKING:
    from ..platform import Platform

MDS_VERSION = "2.0.0"
NS = uuid.UUID("6c1d7f0e-5d55-4a8c-9b0e-000000000000")  # Roam MDS id namespace

EVENT_MAP = {  # Roam vehicle event -> (MDS event_types, vehicle_state)
    "en_route": (["reservation_start"], "reserved"),
    "arrival": (["passenger_arrival"], "reserved"),  # VERIFY name
    "boarding": (["trip_start"], "on_trip"),
    "dropoff": (["trip_end"], "available"),
    "no_show": (["reservation_cancel"], "available"),
    "fault": (["maintenance_pick_up"], "non_operational"),
    "shift_end": (["service_end"], "non_operational"),
}


def _uuid(s: str) -> str:
    return str(uuid.uuid5(NS, s))


def _ms(rt, d: date, minute: float) -> int:
    base = datetime(d.year, d.month, d.day, tzinfo=ZoneInfo(rt.config.timezone))
    return int((base + timedelta(minutes=minute)).timestamp() * 1000)


def mds_vehicles(platform: Platform, tenant_id: str) -> dict[str, Any]:
    rt = platform.tenant(tenant_id)
    return {
        "version": MDS_VERSION,
        "vehicles": [
            {
                "device_id": _uuid(v.id),
                "provider_id": _uuid("roam-mobility"),
                "vehicle_id": v.label,
                "vehicle_type": "car",  # VERIFY: MDS has no 'van'; agencies typically map cutaways to 'car' or 'bus'
                "vehicle_attributes": {"wheelchair_positions": v.wheelchair_positions, "seats": v.seats},
                "propulsion_types": ["combustion"] if v.adapter_kind == AdapterKind.human_driver else ["electric"],
                "accessibility_attributes": ["wheelchair_accessible"] if v.wheelchair_positions else [],
                "automated": v.adapter_kind == AdapterKind.av_partner,
            }
            for v in rt.vehicles
        ],
    }


def mds_events(platform: Platform, tenant_id: str, service_date: date) -> dict[str, Any]:
    rt = platform.tenant(tenant_id)
    out = []
    for e in platform.store.scope(tenant_id).list(Event, service_date=service_date):
        if e.vehicle_id is None or e.type not in EVENT_MAP:
            continue
        types, state = EVENT_MAP[e.type]
        rec: dict[str, Any] = {
            "device_id": _uuid(e.vehicle_id),
            "provider_id": _uuid("roam-mobility"),
            "event_id": _uuid(e.id),
            "event_types": types,
            "vehicle_state": state,
            "timestamp": _ms(rt, service_date, e.timestamp),
        }
        if e.location:
            rec["location"] = {"lat": round(e.location[1], 6), "lng": round(e.location[0], 6)}
        if e.payload.get("trip_id"):
            rec["trip_ids"] = [_uuid(e.payload["trip_id"])]
        out.append(rec)
    return {"version": MDS_VERSION, "events": out}


def mds_trips(platform: Platform, tenant_id: str, service_date: date) -> dict[str, Any]:
    """Completed passenger trips. Rider identity is never exported; locations are rounded."""
    rt = platform.tenant(tenant_id)
    out = []
    for t in platform.store.scope(tenant_id).list(TripRequest, service_date=service_date, status=TripStatus.completed):
        out.append(
            {
                "provider_id": _uuid("roam-mobility"),
                "device_id": _uuid(t.vehicle_id or ""),
                "trip_id": _uuid(t.id),
                "trip_type": ["community_transit" if t.mode.value != "paratransit" else "paratransit"],  # VERIFY vocabulary
                "start_time": _ms(rt, service_date, t.actual_pickup or 0),
                "end_time": _ms(rt, service_date, t.actual_dropoff or 0),
                "start_location": {"lat": round(t.origin[1], 3), "lng": round(t.origin[0], 3)},
                "end_location": {"lat": round(t.destination[1], 3), "lng": round(t.destination[0], 3)},
                "distance": int((t.direct_km or 0) * 1000),
                "accessibility_attributes": ["wheelchair_accessible"] if t.wheelchair else [],
                "passenger_count": 1 + t.companions,
                "fare": {"amount": t.fare, "currency": "USD"},
            }
        )
    return {"version": MDS_VERSION, "trips": out}
