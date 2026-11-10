"""Booking (spec §7.2): one service behind every channel (app, web, IVR, agent).

Paratransit: next-day booking, pickup negotiation within +/-60 min, certified-eligibility
check, standing orders, and **no capacity-constrained denials**. Any denial is logged as
an event and raised to the operations console.
Microtransit: real-time requests, optional walk-to-stop, transfer to fixed route (GTFS).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Literal

from . import geo
from .dispatch.core import Task
from .models import (
    Channel,
    EligibilityStatus,
    Event,
    LonLat,
    Mode,
    Rider,
    StandingOrder,
    TripRequest,
    TripStatus,
    new_id,
)

if TYPE_CHECKING:
    from .platform import Platform

CANCELLABLE = {TripStatus.requested, TripStatus.booked, TripStatus.scheduled, TripStatus.en_route}
ELIGIBLE = {EligibilityStatus.certified, EligibilityStatus.conditional, EligibilityStatus.temporary}
PLANNING_SLACK_MIN = 4.0  # plan to arrive this much inside the promised window (absorbs variance)


class BookingService:
    def __init__(self, platform: Platform):
        self.p = platform

    # --------------------------------------------------------------- helpers
    def _reject(self, trip: TripRequest, reason: str) -> TripRequest:
        trip.status = TripStatus.rejected
        trip.status_reason = reason
        return trip

    @staticmethod
    def _max_ride(direct_min: float, factor: float, extra: float, cap: float) -> float:
        return max(direct_min + 10, min(cap, direct_min * factor + extra))

    def _fare(self, rt, mode: Mode, rider: Rider) -> float:
        f = rt.config.fares.get(mode.value, {})
        if rider.eligibility_status in ELIGIBLE and "reduced" in f and mode != Mode.paratransit:
            return f["reduced"]
        return f.get("base", 0.0)

    def _funding(self, rt, funding_source_id: str | None, rider: Rider) -> str | None:
        if funding_source_id:
            fs = next((f for f in rt.funding if f.id == funding_source_id), None)
            if fs is None:
                raise ValueError(f"unknown funding source {funding_source_id}")
            allowed = fs.rules.get("rider_ids")
            if allowed is not None and rider.id not in allowed:
                raise ValueError(f"rider not authorised on funding source {fs.id}")
            return fs.id
        default = next((f for f in rt.funding if f.type.value in ("city", "county")), rt.funding[0])
        return default.id

    def _snap_to_stop(self, pt: LonLat, stops: list, walk_m: float) -> LonLat:
        if not stops:
            return pt
        best = min(stops, key=lambda s: geo.haversine_km(pt, tuple(s)))
        return tuple(best) if geo.haversine_km(pt, tuple(best)) * 1000 <= walk_m else pt  # type: ignore[return-value]

    def _log_denial(self, rt, trip: TripRequest, reason: str) -> None:
        scope = self.p.store.scope(rt.id)
        scope.add(
            Event(
                id=new_id("evt"),
                tenant_id=rt.id,
                vehicle_id=None,
                type="ada_denial" if trip.mode == Mode.paratransit else "microtransit_unserved",
                timestamp=self.p.clock.minute,
                service_date=trip.service_date,
                location=trip.origin,
                payload={"trip_id": trip.id, "reason": reason},
            )
        )
        self.p.ops.raise_exception(
            type="ada_denial" if trip.mode == Mode.paratransit else "microtransit_unserved",
            severity=3 if trip.mode == Mode.paratransit else 4,
            tenant_id=rt.id,
            at=self.p.clock.minute,
            service_date=self.p.clock.today,
            trip_id=trip.id,
            message=(
                "ADA CAPACITY DENIAL: add capacity or overflow provider immediately"
                if trip.mode == Mode.paratransit
                else "microtransit request unserved"
            ),
        )

    # ---------------------------------------------------------------- main
    def request_trip(
        self,
        tenant_id: str,
        rider_id: str,
        mode: Mode,
        origin: LonLat,
        destination: LonLat,
        service_date: date,
        requested_time: float,
        channel: Channel = Channel.app,
        time_type: Literal["pickup", "appointment"] = "pickup",
        funding_source_id: str | None = None,
        companions: int = 0,
        standing_order_id: str | None = None,
    ) -> TripRequest:
        rt = self.p.tenant(tenant_id)
        scope = self.p.store.scope(tenant_id)
        rider = scope.get(Rider, rider_id)
        origin, destination = tuple(origin), tuple(destination)  # type: ignore[assignment]
        trip = TripRequest(
            id=new_id("trip"),
            tenant_id=tenant_id,
            rider_id=rider_id,
            mode=mode,
            channel=channel,
            origin=origin,
            destination=destination,
            service_date=service_date,
            requested_time=requested_time,
            time_type=time_type,
            wheelchair=rider.uses_wheelchair,
            companions=companions,
            standing_order_id=standing_order_id,
            request_made_at=self.p.clock.minute if service_date == self.p.clock.today else None,
        )
        scope.add(trip)

        if mode not in rt.config.modes:
            return self._reject(trip, f"mode {mode.value} not offered by this tenant")
        try:
            trip.funding_source_id = self._funding(rt, funding_source_id, rider)
        except ValueError as e:
            return self._reject(trip, str(e))
        trip.fare = self._fare(rt, mode, rider)
        hours = rt.config.hours_for(service_date.weekday())
        if hours is None or not (hours[0] <= requested_time <= hours[1]):
            return self._reject(trip, "outside service hours")

        if mode == Mode.paratransit:
            return self._book_paratransit(rt, trip, rider)
        return self._book_microtransit(rt, trip, rider)

    def _book_paratransit(self, rt, trip: TripRequest, rider: Rider) -> TripRequest:
        rules = rt.config.booking_rules.paratransit
        assert rules is not None
        today = self.p.clock.today
        if rider.eligibility_status not in ELIGIBLE or (rider.eligibility_expires and rider.eligibility_expires < trip.service_date):
            return self._reject(trip, "rider is not ADA paratransit certified for this date")
        if not rt.in_service_area(trip.origin, Mode.paratransit) or not rt.in_service_area(trip.destination, Mode.paratransit):
            return self._reject(trip, "origin or destination outside the paratransit service area")
        days_ahead = (trip.service_date - today).days
        if days_ahead < rules.min_advance_days:
            return self._reject(trip, "paratransit requires next-day (or earlier) booking")
        if days_ahead > rules.max_advance_days:
            return self._reject(trip, f"bookings open {rules.max_advance_days} days ahead")
        from .config.schema import hhmm_to_min

        if days_ahead == 1 and self.p.clock.minute > hhmm_to_min(rules.booking_cutoff):
            return self._reject(trip, f"next-day reservations close at {rules.booking_cutoff}")

        direct = rt.travel.travel_min(trip.origin, trip.destination)
        trip.direct_km = rt.travel.distance_km(trip.origin, trip.destination)
        max_ride = self._max_ride(direct, rules.max_ride_factor, rules.max_ride_extra_min, rules.max_ride_cap_min)
        service = rules.wheelchair_service_min if trip.wheelchair else rules.service_min
        d = self.p.dispatcher(rt.id, trip.service_date)
        allowed = d.allowed_units_for(rt.odd_vehicle_ids(trip.origin, trip.destination))

        if trip.time_type == "pickup":
            base = trip.requested_time
            offsets = [0, 15, -15, 30, -30, 45, -45, 60, -60]
            do_latest = float("inf")
        else:
            base = trip.requested_time - max_ride
            offsets = [0, 15, -15, -30, -45, -60]
            do_latest = trip.requested_time
        offsets = [o for o in offsets if abs(o) <= rules.negotiation_window_min]
        # pass 1: insertion into the current plan; pass 2: repair (move one booked trip) before any denial
        for attempt, off in [("insert", o) for o in offsets] + [("repair", o) for o in offsets]:
            P = base + off
            task = Task(
                trip_id=trip.id,
                pickup=trip.origin,
                dropoff=trip.destination,
                pu_earliest=P - rules.early_window_min,
                pu_latest=P + rules.pickup_window_min - PLANNING_SLACK_MIN,
                max_ride=max_ride,
                seats=trip.seats,
                wc=1 if trip.wheelchair else 0,
                pu_service=service,
                do_service=service,
                do_latest=do_latest,
                allowed_units=allowed,
                priority=1,
            )
            ok = d.try_insert(task) is not None if attempt == "insert" else d.repair_insert(task)
            if ok:
                trip.negotiated_pickup = P
                trip.window = (P, P + rules.pickup_window_min)
                trip.status = TripStatus.booked
                trip.status_reason = "" if off == 0 else f"negotiated {off:+d} min from requested time"
                return trip
        trip.status = TripStatus.denied
        trip.status_reason = "no capacity within the +/-60 min negotiation window"
        self._log_denial(rt, trip, trip.status_reason)
        return trip

    def _book_microtransit(self, rt, trip: TripRequest, rider: Rider) -> TripRequest:
        mode = trip.mode
        rules = getattr(rt.config.booking_rules, mode.value)
        assert rules is not None
        origin = self._snap_to_stop(trip.origin, rules.virtual_stops, rules.walk_to_stop_m)
        dest = self._snap_to_stop(trip.destination, rules.virtual_stops, rules.walk_to_stop_m)
        if not rt.in_service_area(origin, mode):
            return self._reject(trip, "pickup outside the service zone")
        if not rt.in_service_area(dest, mode):
            stop = self._transfer_stop(rt, dest, mode)
            if stop is None:
                return self._reject(trip, "destination outside the service zone")
            dest = (stop["lon"], stop["lat"])
            trip.status_reason = f"transfer to fixed route at {stop['stop_name']} ({stop['stop_id']})"
        trip.origin, trip.destination = origin, dest
        today, now = self.p.clock.today, self.p.clock.minute
        days_ahead = (trip.service_date - today).days
        if days_ahead < 0 or days_ahead > rules.max_advance_days:
            return self._reject(trip, "booking date out of range")
        realtime = days_ahead == 0 and trip.requested_time <= now + 5
        if days_ahead == 0 and trip.requested_time < now - 5:
            return self._reject(trip, "requested time is in the past")
        start = now if realtime else trip.requested_time
        direct = rt.travel.travel_min(origin, dest)
        trip.direct_km = rt.travel.distance_km(origin, dest)
        service = rules.wheelchair_service_min if trip.wheelchair else rules.service_min
        latest = start + (rules.max_wait_min if realtime else rules.pickup_window_min)
        task = Task(
            trip_id=trip.id,
            pickup=origin,
            dropoff=dest,
            pu_earliest=start,
            pu_latest=latest,
            max_ride=self._max_ride(direct, rules.max_ride_factor, rules.max_ride_extra_min, rules.max_ride_cap_min),
            seats=trip.seats,
            wc=1 if trip.wheelchair else 0,
            pu_service=service,
            do_service=service,
        )
        d = self.p.dispatcher(rt.id, trip.service_date)
        task.allowed_units = d.allowed_units_for(rt.odd_vehicle_ids(origin, dest))
        ins = d.try_insert(task, now=now if days_ahead == 0 else None)
        if ins is None:
            trip.status = TripStatus.denied
            trip.status_reason = "no vehicle can reach you in time; try a later time"
            self._log_denial(rt, trip, trip.status_reason)
            return trip
        planned = d.planned_pickup(trip.id) or start
        task.pu_latest = min(task.pu_latest, max(planned, start) + rules.pickup_window_min)
        trip.negotiated_pickup = round(planned, 1)
        trip.window = (start, task.pu_latest)
        trip.status = TripStatus.booked
        return trip

    def _transfer_stop(self, rt, dest: LonLat, mode: Mode) -> dict | None:
        """Nearest GTFS fixed-route stop inside the zone, toward the rider's destination."""
        cands = [s for s in rt.gtfs_stops if rt.in_service_area((s["lon"], s["lat"]), mode)]
        if not cands:
            return None
        return min(cands, key=lambda s: geo.haversine_km((s["lon"], s["lat"]), dest))

    # ----------------------------------------------------------- lifecycle
    def cancel_trip(self, tenant_id: str, trip_id: str, reason: str = "rider request") -> TripRequest:
        scope = self.p.store.scope(tenant_id)
        trip = scope.get(TripRequest, trip_id)
        if trip.status not in CANCELLABLE:  # closed trips (incl. ADA denials) are final records
            raise ValueError(f"cannot cancel a trip in status {trip.status.value}")
        d = self.p.dispatchers.get((tenant_id, trip.service_date))
        if d is not None:
            d.remove_trip(trip_id)
        late = (
            trip.service_date == self.p.clock.today
            and trip.negotiated_pickup is not None
            and trip.negotiated_pickup - self.p.clock.minute < 120
        )
        trip.status = TripStatus.cancelled
        trip.status_reason = reason + (" (late cancellation)" if late else "")
        return trip

    def add_standing_order(self, order: StandingOrder) -> StandingOrder:
        return self.p.store.scope(order.tenant_id).add(order)

    def expand_standing_orders(self, tenant_id: str, service_date: date) -> list[TripRequest]:
        """Nightly job: book every subscription trip that falls on ``service_date``."""
        scope = self.p.store.scope(tenant_id)
        out = []
        for so in scope.list(StandingOrder):
            if service_date.weekday() not in so.weekdays or service_date < so.start or (so.end and service_date > so.end):
                continue
            if any(t.standing_order_id == so.id and t.service_date == service_date for t in scope.list(TripRequest)):
                continue
            out.append(
                self.request_trip(
                    tenant_id,
                    so.rider_id,
                    Mode.paratransit,
                    so.origin,
                    so.destination,
                    service_date,
                    so.requested_time,
                    Channel.agent,
                    so.time_type,
                    so.funding_source_id,
                    standing_order_id=so.id,
                )
            )
        return out
