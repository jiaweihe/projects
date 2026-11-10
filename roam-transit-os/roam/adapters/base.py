"""Vehicle adapter interface (spec §6): human driver and AV are just adapters.

Python mirror of the TypeScript interface in the spec. Methods are synchronous in the
MVP (the simulator drives them in-process); network-backed adapters can wrap an async
client internally.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from ..models import AdapterKind, LonLat, Run, VehicleCapabilities


@dataclass
class Ack:
    ok: bool
    message: str = ""


@dataclass
class RunPatch:
    add_stops: list[Any] = field(default_factory=list)  # the run's open stops, in their new order


@dataclass
class Telemetry:
    vehicle_id: str
    timestamp: float
    location: LonLat
    speed_kmh: float = 0.0
    state_of_charge: float | None = None  # 0..1
    odometer_km: float = 0.0


@dataclass
class VehicleEvent:
    vehicle_id: str
    timestamp: float
    type: Literal["arrival", "boarding", "dropoff", "no_show", "fault", "remote_assist", "shift_end"]
    stop_id: str | None = None
    trip_id: str | None = None
    location: LonLat | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssistContext:
    vehicle_id: str
    timestamp: float
    location: LonLat
    reason: str
    riders_onboard: int = 0


@dataclass
class AssistTicket:
    ticket_id: str
    vehicle_id: str
    status: Literal["open", "acknowledged", "resolved"] = "open"


TelemetryCb = Callable[[Telemetry], None]
EventCb = Callable[[VehicleEvent], None]


class VehicleAdapter(ABC):
    kind: AdapterKind

    def __init__(self, vehicle_id: str, capabilities: VehicleCapabilities):
        self.vehicle_id = vehicle_id
        self.capabilities = capabilities
        self._telemetry_cbs: list[TelemetryCb] = []
        self._event_cbs: list[EventCb] = []

    @abstractmethod
    def assign_run(self, run: Run) -> Ack: ...

    @abstractmethod
    def update_run(self, run_id: str, patch: RunPatch) -> Ack: ...

    @abstractmethod
    def cancel_stop(self, stop_id: str, reason: str) -> Ack: ...

    def on_telemetry(self, cb: TelemetryCb) -> None:
        self._telemetry_cbs.append(cb)

    def on_event(self, cb: EventCb) -> None:
        self._event_cbs.append(cb)

    def request_remote_assist(self, ctx: AssistContext) -> AssistTicket | None:  # optional capability
        return None

    # helpers for subclasses
    def _emit_telemetry(self, t: Telemetry) -> None:
        for cb in self._telemetry_cbs:
            cb(t)

    def _emit_event(self, e: VehicleEvent) -> None:
        for cb in self._event_cbs:
            cb(e)
