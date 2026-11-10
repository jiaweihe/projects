"""Simulator adapter (spec §6): a vehicle that drives in a discrete-event world.

Used for testing, for the proposal generator, and as the stand-in for AV providers
until a real fleet API is available.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ..geo import TravelModel
from ..models import AdapterKind, LonLat, Run, Stop, StopStatus, StopType, VehicleCapabilities
from ..sim.world import SimWorld
from .base import Ack, RunPatch, Telemetry, VehicleAdapter, VehicleEvent


@dataclass
class SimParams:
    travel_noise_sd: float = 0.12  # lognormal sigma on each leg's travel time
    no_show_rate: float = 0.03
    no_show_wait_min: float = 5.0
    fault_rate_per_hour: float = 0.0
    avg_speed_kmh: float = 32.0
    battery_km: float | None = None  # if set, report state of charge


class SimulatorAdapter(VehicleAdapter):
    kind = AdapterKind.simulator

    def __init__(
        self,
        vehicle_id: str,
        capabilities: VehicleCapabilities,
        world: SimWorld,
        travel: TravelModel,
        start_loc: LonLat,
        params: SimParams | None = None,
        rng: random.Random | None = None,
    ):
        super().__init__(vehicle_id, capabilities)
        self.world = world
        self.travel = travel
        self.params = params or SimParams()
        self.rng = rng or random.Random(hash(vehicle_id) & 0xFFFF)
        self.loc: LonLat = start_loc
        self.home: LonLat = start_loc
        self.runs: list[Run] = []
        self._finished: dict[str, Run] = {}
        self._cancelled: set[str] = set()
        self.current: Run | None = None
        self.pending: list[Stop] = []
        self.busy = False  # en route or serving a stop
        self.faulted = False
        self.odometer = 0.0
        self.run_km = 0.0
        self._last_t = world.now

    # ----------------------------------------------------------- interface
    def assign_run(self, run: Run) -> Ack:
        self.runs.append(run)
        self.runs.sort(key=lambda r: r.shift_start if r.shift_start is not None else (r.stops[0].earliest if r.stops else 0))
        if not self.busy and self.current is None:
            self.world.schedule(self.world.now, self._next)
        return Ack(True)

    def update_run(self, run_id: str, patch: RunPatch) -> Ack:
        new = list(patch.add_stops)
        if self.current is not None and self.current.id == run_id:
            self.pending = new
            self.current.stops = new
            if not self.busy:
                self.world.schedule(self.world.now, self._next)
            return Ack(True)
        for r in self.runs:
            if r.id == run_id:
                r.stops = new
                return Ack(True)
        done = self._finished.get(run_id)
        if done is not None and new:  # stops added to a run the vehicle already finished: reopen it
            done.stops = new
            done.status = "active"
            del self._finished[run_id]
            if self.current is None:
                self.current, self.pending = done, list(new)
                if not self.busy:
                    self.world.schedule(self.world.now, self._next)
            else:
                self.runs.insert(0, done)
            return Ack(True)
        return Ack(False, f"unknown run {run_id}")

    def cancel_stop(self, stop_id: str, reason: str) -> Ack:
        self._cancelled.add(stop_id)  # also covers the stop the vehicle is currently driving to
        before = len(self.pending)
        self.pending = [s for s in self.pending if s.id != stop_id]
        return Ack(True, "" if len(self.pending) < before else "stop in progress; will be skipped")

    # ------------------------------------------------------------ dynamics
    def _event(self, type_: str, stop: Stop | None = None, **payload) -> None:
        payload.setdefault("run_id", self.current.id if self.current else None)
        payload["odometer"] = self.run_km
        self._emit_event(
            VehicleEvent(
                vehicle_id=self.vehicle_id,
                timestamp=self.world.now,
                type=type_,  # type: ignore[arg-type]
                stop_id=stop.id if stop else None,
                trip_id=stop.trip_request_id if stop else None,
                location=self.loc,
                payload=payload,
            )
        )

    def _telemetry(self) -> None:
        soc = None
        if self.params.battery_km:
            soc = max(0.0, 1 - self.odometer / self.params.battery_km)
        self._emit_telemetry(Telemetry(self.vehicle_id, self.world.now, self.loc, 0.0, soc, self.odometer))

    def _maybe_fault(self) -> bool:
        rate = self.params.fault_rate_per_hour
        if rate <= 0:
            return False
        dt = (self.world.now - self._last_t) / 60
        self._last_t = self.world.now
        if self.rng.random() < 1 - math.exp(-rate * dt):
            self.faulted = True
            self._event("fault", reason="simulated mechanical fault")
            return True
        return False

    def _next(self) -> None:
        if self.faulted or self.busy:
            return
        if self.current is None or not self.pending:
            if self.current is not None:
                # nothing to do yet: stay on this run, idle where we are, until it is time to head home
                home_min = self.travel.travel_min(self.loc, self.home)
                if self.current.shift_end is not None and self.world.now < self.current.shift_end - home_min - 1:
                    self.world.schedule(self.current.shift_end - home_min, self._next)
                    return
                if self.loc != self.home:  # deadhead back to the depot at end of run
                    km = self.travel.distance_km(self.loc, self.home)
                    tt = self.travel.travel_min(self.loc, self.home)
                    self.busy = True

                    def at_depot() -> None:
                        self.loc = self.home
                        self.odometer += km
                        self.run_km += km
                        self._event("shift_end")
                        self.busy = False
                        self._next()

                    self.world.schedule(self.world.now + tt, at_depot)
                    return
                self.current.status = "completed"
                self._finished[self.current.id] = self.current
                self.current = None
            if not self.runs:
                return
            nxt = self.runs.pop(0)
            self.current = nxt
            nxt.status = "active"
            self.pending = list(nxt.stops)
            self.run_km = 0.0
            self.loc = self.loc  # vehicle continues from where it is
            if not self.pending:
                self.world.schedule(self.world.now, self._next)
                return
        if self._maybe_fault():
            return
        # stay uncommitted (dispatcher may still insert ahead) until it is time to leave
        nxt = self.pending[0]
        lead = 0.0 if nxt.location is None else self.travel.travel_min(self.loc, nxt.location)
        depart_at = nxt.earliest - lead - 2.0
        if self.world.now < depart_at:
            self.world.schedule(depart_at, self._next)
            return
        stop = self.pending.pop(0)
        self.busy = True
        if stop.type == StopType.break_ or stop.location is None:
            self._event("en_route", stop, eta=self.world.now)
            start = max(self.world.now, stop.earliest)
            self.world.schedule(start + stop.service_min, self._done)
            return
        planned = self.travel.travel_min(self.loc, stop.location)
        actual = planned * math.exp(self.rng.gauss(-self.params.travel_noise_sd**2 / 2, self.params.travel_noise_sd))
        self._event("en_route", stop, eta=self.world.now + planned)
        km = self.travel.distance_km(self.loc, stop.location)
        self.world.schedule(self.world.now + actual, lambda: self._arrive(stop, km))

    def _arrive(self, stop: Stop, km: float) -> None:
        self.loc = stop.location  # type: ignore[assignment]
        self.odometer += km
        self.run_km += km
        if stop.id in self._cancelled:  # cancelled while en route: drive on
            stop.status = StopStatus.cancelled
            self._done()
            return
        stop.status = StopStatus.arrived
        stop.actual = self.world.now
        self._event("arrival", stop)
        self._telemetry()
        start = max(self.world.now, stop.earliest)
        self.world.schedule(start, lambda: self._serve(stop))

    def _serve(self, stop: Stop) -> None:
        if stop.type == StopType.pickup and self.rng.random() < self.params.no_show_rate:
            wait = self.params.no_show_wait_min

            def no_show() -> None:
                stop.status = StopStatus.no_show
                self.busy = False
                self._event("no_show", stop)
                self._next()

            self.world.schedule(self.world.now + wait, no_show)
            return
        stop.status = StopStatus.done
        self._event("boarding" if stop.type == StopType.pickup else "dropoff", stop)
        self.world.schedule(self.world.now + stop.service_min, self._done)

    def _done(self) -> None:
        self.busy = False
        self._next()
