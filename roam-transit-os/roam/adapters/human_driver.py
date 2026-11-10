"""Human-driver adapter, backed by the Roam driver app (spec §5, §6).

The driver app polls (or subscribes to) its manifest and posts stop actions back. This
adapter holds the manifest server-side and turns driver actions into ``VehicleEvent``s.
It also enforces the wheelchair securement checklist before a wheelchair boarding can be
confirmed.
"""

from __future__ import annotations

from typing import Any

from ..models import AdapterKind, Run, Stop, StopStatus, StopType, VehicleCapabilities
from .base import Ack, RunPatch, Telemetry, VehicleAdapter, VehicleEvent

SECUREMENT_CHECKLIST = (
    "four_point_tiedowns_attached",
    "lap_and_shoulder_belt_offered",
    "wheelchair_brakes_set",
    "ramp_or_lift_stowed",
)


class HumanDriverAdapter(VehicleAdapter):
    kind = AdapterKind.human_driver

    def __init__(self, vehicle_id: str, capabilities: VehicleCapabilities):
        super().__init__(vehicle_id, capabilities)
        self.runs: dict[str, Run] = {}
        self.manifest_version = 0
        self.messages: list[dict[str, Any]] = []  # pushed to the driver app (SMS/push in production)
        self.heading_to: set[str] = set()  # stops the driver has departed for (committed)

    def assign_run(self, run: Run) -> Ack:
        self.runs[run.id] = run
        self._bump("new_run", run_id=run.id)
        return Ack(True)

    def update_run(self, run_id: str, patch: RunPatch) -> Ack:
        run = self.runs.get(run_id)
        if run is None:
            return Ack(False, "unknown run")
        # keep served stops and the stop the driver is already driving to; the dispatcher's
        # patch only lists stops that are still open for re-planning
        done = [s for s in run.stops if s.status != StopStatus.planned or s.id in self.heading_to]
        run.stops = done + [s for s in patch.add_stops if s.id not in {d.id for d in done}]
        self._bump("manifest_changed", run_id=run_id)
        return Ack(True)

    def cancel_stop(self, stop_id: str, reason: str) -> Ack:
        for run in self.runs.values():
            for s in run.stops:
                if s.id == stop_id and s.status == StopStatus.planned:
                    s.status = StopStatus.cancelled
                    self.heading_to.discard(stop_id)
                    self._bump("stop_cancelled", stop_id=stop_id, reason=reason)
                    return Ack(True)
        return Ack(False, "stop not found or already served")

    def _bump(self, kind: str, **kw: Any) -> None:
        self.manifest_version += 1
        self.messages.append({"kind": kind, "version": self.manifest_version, **kw})

    # ------------------------------------------------------ driver app side
    def manifest(self) -> dict[str, Any]:
        stops = [
            s.model_dump()
            for r in sorted(self.runs.values(), key=lambda r: r.id)
            for s in r.stops
            if s.status in (StopStatus.planned, StopStatus.arrived)
        ]
        return {"vehicle_id": self.vehicle_id, "version": self.manifest_version, "stops": stops}

    def _find(self, stop_id: str) -> tuple[Run, Stop]:
        for r in self.runs.values():
            for s in r.stops:
                if s.id == stop_id:
                    return r, s
        raise KeyError(stop_id)

    def driver_action(
        self,
        stop_id: str,
        action: str,
        timestamp: float,
        location: tuple[float, float] | None = None,
        checklist: dict[str, bool] | None = None,
        wheelchair: bool = False,
    ) -> Ack:
        """Driver app posts: depart (toward stop), arrive, board, no_show, dropoff."""
        run, stop = self._find(stop_id)
        if stop.status in (StopStatus.cancelled, StopStatus.done, StopStatus.no_show):
            return Ack(False, f"stop is {stop.status.value}")
        if action == "board" and wheelchair:
            missing = [k for k in SECUREMENT_CHECKLIST if not (checklist or {}).get(k)]
            if missing:
                return Ack(False, f"securement checklist incomplete: {', '.join(missing)}")
        etype = {"depart": "en_route", "arrive": "arrival", "board": "boarding", "no_show": "no_show", "dropoff": "dropoff"}.get(action)
        if etype is None:
            return Ack(False, f"unknown action {action}")
        if action == "no_show" and stop.type != StopType.pickup:
            return Ack(False, "no_show only valid at a pickup")
        if action == "dropoff":
            pickup = next((s for r in self.runs.values() for s in r.stops if s.id == f"{stop.trip_request_id}:pu"), None)
            if pickup is not None and pickup.status != StopStatus.done:
                return Ack(False, "rider has not boarded")
        if action == "depart":
            self.heading_to.add(stop_id)
        elif action == "arrive":
            stop.status, stop.actual = StopStatus.arrived, timestamp
        elif action in ("board", "dropoff"):
            stop.status = StopStatus.done
            self.heading_to.discard(stop_id)
        elif action == "no_show":
            stop.status = StopStatus.no_show
        self._emit_event(
            VehicleEvent(
                vehicle_id=self.vehicle_id,
                timestamp=timestamp,
                type=etype,  # type: ignore[arg-type]
                stop_id=stop_id,
                trip_id=stop.trip_request_id,
                location=location,
                payload={"run_id": run.id, "eta": timestamp},
            )
        )
        return Ack(True)

    def driver_telemetry(self, timestamp: float, location: tuple[float, float], speed_kmh: float = 0.0, odometer_km: float = 0.0) -> None:
        self._emit_telemetry(Telemetry(self.vehicle_id, timestamp, location, speed_kmh, None, odometer_km))

    def report_fault(self, timestamp: float, location: tuple[float, float], reason: str) -> None:
        run_id = next(iter(self.runs), None)
        self._emit_event(VehicleEvent(self.vehicle_id, timestamp, "fault", location=location, payload={"run_id": run_id, "reason": reason}))
