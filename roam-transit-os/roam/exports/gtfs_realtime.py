"""GTFS-Realtime feeds (vehicle positions, trip updates), spec §7.7.

Emits the FeedMessage structure as JSON (the GTFS-RT JSON mapping). If the optional
``gtfs-realtime-bindings`` package is installed, :func:`to_protobuf` serialises the same
feed to the binary format that trip planners consume.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..models import TripRequest, TripStatus

if TYPE_CHECKING:
    from ..platform import Platform


def _epoch(rt, service_date: date, minute: float) -> int:
    base = datetime(service_date.year, service_date.month, service_date.day, tzinfo=ZoneInfo(rt.config.timezone))
    return int((base + timedelta(minutes=minute)).timestamp())


def vehicle_positions(platform: Platform, tenant_id: str, service_date: date) -> dict[str, Any]:
    rt = platform.tenant(tenant_id)
    entities = []
    for v in rt.vehicles:
        t = platform.telemetry.get(v.id)
        if t is None:
            continue
        entities.append(
            {
                "id": v.id,
                "vehicle": {
                    "vehicle": {"id": v.id, "label": v.label, "wheelchair_accessible": 1 if v.wheelchair_positions else 2},
                    "position": {"latitude": t.location[1], "longitude": t.location[0], "speed": t.speed_kmh / 3.6},
                    "timestamp": _epoch(rt, service_date, t.timestamp),
                },
            }
        )
    return {"header": {"gtfs_realtime_version": "2.0", "incrementality": "FULL_DATASET", "timestamp": int(time.time())}, "entity": entities}


def trip_updates(platform: Platform, tenant_id: str, service_date: date) -> dict[str, Any]:
    """Demand-responsive trip updates: one entity per active rider trip, with pickup/drop-off ETAs."""
    rt = platform.tenant(tenant_id)
    d = platform.dispatchers.get((tenant_id, service_date))
    entities = []
    scope = platform.store.scope(tenant_id)
    for trip in scope.list(TripRequest, service_date=service_date):
        if trip.status not in (TripStatus.scheduled, TripStatus.en_route, TripStatus.onboard, TripStatus.booked):
            continue
        eta = d.planned_pickup(trip.id) if d else None
        stus = []
        if eta is not None:
            stus.append({"stop_sequence": 1, "arrival": {"time": _epoch(rt, service_date, eta)}})
        update: dict[str, Any] = {
            "trip": {"trip_id": trip.id, "start_date": service_date.strftime("%Y%m%d"), "schedule_relationship": "ADDED"},
            "stop_time_update": stus,
        }
        if trip.vehicle_id:  # omit rather than emit null (protobuf converters reject nulls)
            update["vehicle"] = {"id": trip.vehicle_id}
        entities.append({"id": trip.id, "trip_update": update})
    return {"header": {"gtfs_realtime_version": "2.0", "incrementality": "FULL_DATASET", "timestamp": int(time.time())}, "entity": entities}


def to_protobuf(feed: dict[str, Any]) -> bytes:  # pragma: no cover - optional dependency
    from google.protobuf import json_format
    from google.transit import gtfs_realtime_pb2

    msg = gtfs_realtime_pb2.FeedMessage()
    json_format.ParseDict(feed, msg, ignore_unknown_fields=True)
    return msg.SerializeToString()
