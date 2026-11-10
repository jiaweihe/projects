"""Multi-city operations center (Roam service layer, spec §7.4).

One seat supervises many tenants. The exceptions queue is ranked by severity, then age.
Agent load (tenants, vehicles and exception-minutes per seat) is a first-class metric
because it drives the venture's economics (spec §2.5).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..models import Severity

_ids = itertools.count(1)

# Expected handling time per exception type, minutes (PLACEHOLDER: calibrate from pilot data).
HANDLE_MIN: dict[str, float] = {
    "vehicle_fault": 12,
    "rescue_failed": 15,
    "reassign_failed": 8,
    "remote_assist": 4,
    "ada_denial": 6,
    "late_pickup": 1.5,
    "predicted_late_pickup": 1.0,
    "no_show": 0.5,
    "incident": 20,
    "incident_notice_undelivered": 5,
    "ivr_human_fallback": 4,
    "microtransit_unserved": 0.5,
    "complaint": 3,
}


@dataclass
class OpsException:
    id: str
    tenant_id: str
    type: str
    severity: int
    service_date: date | None
    at: float  # minute of day
    message: str = ""
    vehicle_id: str | None = None
    trip_id: str | None = None
    status: str = "open"  # open | acknowledged | resolved
    assigned_to: str | None = None
    acked_at: float | None = None
    resolved_at: float | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def handle_min(self) -> float:
        return HANDLE_MIN.get(self.type, 3.0)

    def sort_key(self) -> tuple:
        return (self.severity, self.at, self.id)


@dataclass
class Seat:
    id: str
    name: str
    tenant_ids: set[str]


class OpsCenter:
    def __init__(self) -> None:
        self.exceptions: dict[str, OpsException] = {}
        self.seats: dict[str, Seat] = {}
        self.vehicle_counts: dict[str, int] = {}

    # ------------------------------------------------------------ seats
    def add_seat(self, seat_id: str, name: str, tenant_ids: set[str]) -> Seat:
        s = Seat(seat_id, name, set(tenant_ids))
        self.seats[seat_id] = s
        return s

    def register_tenant(self, tenant_id: str, vehicles: int) -> None:
        self.vehicle_counts[tenant_id] = vehicles

    # ------------------------------------------------------- exceptions
    def raise_exception(
        self,
        *,
        type: str,
        severity: int,
        tenant_id: str,
        at: float,
        message: str = "",
        vehicle_id: str | None = None,
        trip_id: str | None = None,
        service_date: date | None = None,
        **data: Any,
    ) -> OpsException:
        ex = OpsException(
            id=f"exc_{next(_ids):06d}",
            tenant_id=tenant_id,
            type=type,
            severity=int(severity),
            service_date=service_date,
            at=at,
            message=message,
            vehicle_id=vehicle_id,
            trip_id=trip_id,
            data=data,
        )
        self.exceptions[ex.id] = ex
        return ex

    def queue(self, seat_id: str | None = None, tenant_ids: set[str] | None = None, include_closed: bool = False) -> list[OpsException]:
        allowed = tenant_ids if tenant_ids is not None else (self.seats[seat_id].tenant_ids if seat_id else None)
        items = [
            e
            for e in self.exceptions.values()
            if (allowed is None or e.tenant_id in allowed) and (include_closed or e.status != "resolved")
        ]
        return sorted(items, key=OpsException.sort_key)

    def acknowledge(self, exc_id: str, seat_id: str | None, at: float) -> OpsException:
        e = self.exceptions[exc_id]
        seat = self.seats.get(seat_id or "")
        if seat is not None and e.tenant_id not in seat.tenant_ids:
            raise PermissionError("seat not assigned to this tenant")
        e.status, e.assigned_to, e.acked_at = "acknowledged", seat_id, at
        return e

    def resolve(self, exc_id: str, at: float, note: str = "") -> OpsException:
        e = self.exceptions[exc_id]
        e.status, e.resolved_at = "resolved", at
        if note:
            e.data["resolution"] = note
        return e

    # ------------------------------------------------------------ load
    def seat_load(self, seat_id: str, window_min: float) -> dict[str, float]:
        seat = self.seats[seat_id]
        exc = [e for e in self.exceptions.values() if e.tenant_id in seat.tenant_ids]
        work = sum(e.handle_min for e in exc)
        return {
            "tenants": len(seat.tenant_ids),
            "vehicles": sum(self.vehicle_counts.get(t, 0) for t in seat.tenant_ids),
            "exceptions": len(exc),
            "exceptions_per_hour": len(exc) / (window_min / 60) if window_min else 0.0,
            "utilization": work / window_min if window_min else 0.0,
        }

    def simulate_seat(self, seat_id: str, start: float, end: float, service_date: date | None = None) -> dict[str, float]:
        """Replay the day's exceptions through one seat (single server, priority queue).

        Returns response-time statistics: proof that one seat can supervise N tenants.
        """
        seat = self.seats[seat_id]
        arrivals = sorted(
            (
                e
                for e in self.exceptions.values()
                if e.tenant_id in seat.tenant_ids and (service_date is None or e.service_date == service_date)
            ),
            key=lambda e: e.at,
        )
        t = start
        waiting: list[OpsException] = []
        i = 0
        response: dict[int, list[float]] = {}
        busy = 0.0
        while i < len(arrivals) or waiting:
            while i < len(arrivals) and arrivals[i].at <= t:
                waiting.append(arrivals[i])
                i += 1
            if not waiting:
                t = arrivals[i].at
                continue
            waiting.sort(key=OpsException.sort_key)
            e = waiting.pop(0)
            e.status, e.assigned_to, e.acked_at = "acknowledged", seat_id, t
            response.setdefault(e.severity, []).append(t - e.at)
            t += e.handle_min
            busy += e.handle_min
            e.status, e.resolved_at = "resolved", t
        out = {
            "tenants": len(seat.tenant_ids),
            "vehicles": sum(self.vehicle_counts.get(x, 0) for x in seat.tenant_ids),
            "exceptions": len(arrivals),
            "utilization": busy / max(1.0, end - start),
        }
        for sev, vals in response.items():
            vals.sort()
            name = Severity(sev).name
            out[f"p95_response_min_{name}"] = vals[min(len(vals) - 1, math.ceil(0.95 * len(vals)) - 1)]
            out[f"max_response_min_{name}"] = vals[-1]
        return out


def ops_sink(ops: OpsCenter, service_date: date | None):
    """Adapter from dispatcher ``on_exception(**kw)`` callbacks to the ops center."""

    def sink(**kw: Any) -> OpsException | None:
        kw.setdefault("service_date", service_date)
        return ops.raise_exception(**kw)

    return sink
