from datetime import timedelta

from roam.models import AccessibilityNeed, Channel, EligibilityStatus, Mode, Rider, StandingOrder, TripStatus

from .conftest import SERVICE_DAY, TODAY

A, B = (-75.05, 40.06), (-75.00, 40.03)
OUTSIDE = (-75.5, 40.5)


def _rider(p, tid="testville", **kw):
    kw.setdefault("eligibility_status", EligibilityStatus.certified)
    r = Rider(id=f"rider_{len(p.store.scope(tid).list(Rider)) + 1:04d}", tenant_id=tid, **kw)
    return p.store.scope(tid).add(r)


def test_paratransit_next_day_booking_and_window(testville):
    p, rt = testville
    p.clock.minute = 600
    r = _rider(p)
    t = p.booking.request_trip("testville", r.id, Mode.paratransit, A, B, SERVICE_DAY, 9 * 60, Channel.web)
    assert t.status == TripStatus.booked
    assert t.window[1] - t.window[0] == 30
    assert abs(t.negotiated_pickup - 540) <= 60


def test_paratransit_rules(testville):
    p, rt = testville
    p.clock.minute = 600
    r = _rider(p)
    same_day = p.booking.request_trip("testville", r.id, Mode.paratransit, A, B, TODAY, 900)
    assert same_day.status == TripStatus.rejected and "next-day" in same_day.status_reason
    outside = p.booking.request_trip("testville", r.id, Mode.paratransit, A, OUTSIDE, SERVICE_DAY, 600)
    assert outside.status == TripStatus.rejected
    ineligible = _rider(p, eligibility_status=EligibilityStatus.none)
    t = p.booking.request_trip("testville", ineligible.id, Mode.paratransit, A, B, SERVICE_DAY, 600)
    assert t.status == TripStatus.rejected and "certified" in t.status_reason
    late = p.booking.request_trip("testville", r.id, Mode.paratransit, A, B, SERVICE_DAY, 23 * 60)
    assert late.status == TripStatus.rejected and "hours" in late.status_reason
    p.clock.minute = 18 * 60
    after_cutoff = p.booking.request_trip("testville", r.id, Mode.paratransit, A, B, SERVICE_DAY, 600)
    assert after_cutoff.status == TripStatus.rejected and "close" in after_cutoff.status_reason


def test_capacity_denial_is_logged_and_alerted(testville):
    """Saturate the fleet at one moment: any denial must be an event + ops exception, never silent."""
    p, rt = testville
    p.clock.minute = 600
    results = []
    for i in range(30):
        r = _rider(p, accessibility_needs=[AccessibilityNeed.wheelchair])
        results.append(p.booking.request_trip("testville", r.id, Mode.paratransit, A, B, SERVICE_DAY, 7 * 60))
    denied = [t for t in results if t.status == TripStatus.denied]
    assert denied, "test expects saturation"
    alerts = [e for e in p.ops.exceptions.values() if e.type == "ada_denial"]
    assert len(alerts) == len(denied)
    from roam.models import Event

    assert len([e for e in p.store.scope("testville").list(Event) if e.type == "ada_denial"]) == len(denied)


def test_standing_orders_expand_once(testville):
    p, rt = testville
    p.clock.minute = 600
    r = _rider(p)
    p.booking.add_standing_order(StandingOrder(id="so1", tenant_id="testville", rider_id=r.id, weekdays=[1, 3], origin=A,
                                               destination=B, requested_time=480, start=TODAY))
    first = p.booking.expand_standing_orders("testville", SERVICE_DAY)  # Tuesday
    again = p.booking.expand_standing_orders("testville", SERVICE_DAY)
    assert len(first) == 1 and first[0].status == TripStatus.booked and again == []
    assert p.booking.expand_standing_orders("testville", SERVICE_DAY + timedelta(days=1)) == []  # Wednesday is not a standing-order day


def test_cancel_removes_from_plan(testville):
    p, rt = testville
    p.clock.minute = 600
    r = _rider(p)
    t = p.booking.request_trip("testville", r.id, Mode.paratransit, A, B, SERVICE_DAY, 600)
    p.booking.cancel_trip("testville", t.id)
    d = p.dispatcher("testville", SERVICE_DAY)
    assert t.id not in d.tasks and all(n.trip_id != t.id for u in d.units for n in u.route)


def test_microtransit_realtime_and_walk_to_stop(platform):
    from roam.config.schema import config_from_dict

    from .conftest import new_city_config

    cfg = new_city_config()
    cfg["booking_rules"]["microtransit"]["virtual_stops"] = [[-75.0505, 40.0605]]
    p = platform
    p.provision(config_from_dict(cfg))
    p.clock.today, p.clock.minute = SERVICE_DAY, 600
    r = p.store.scope("testville").add(Rider(id="rider_m", tenant_id="testville"))
    t = p.booking.request_trip("testville", r.id, Mode.microtransit, A, B, SERVICE_DAY, 600)
    assert t.status == TripStatus.booked
    assert t.origin == (-75.0505, 40.0605)  # snapped to the virtual stop within walking distance
    assert 600 <= t.negotiated_pickup <= 630


def test_closed_trips_cannot_be_cancelled_so_denials_stay_on_record(testville):
    """Cancelling a denied trip would erase an ADA denial from the KPIs; closed trips are final."""
    import pytest

    p, rt = testville
    p.clock.minute = 600
    r = _rider(p)
    rejected = p.booking.request_trip("testville", r.id, Mode.paratransit, A, OUTSIDE, SERVICE_DAY, 600)
    booked = p.booking.request_trip("testville", r.id, Mode.paratransit, A, B, SERVICE_DAY, 600)
    p.booking.cancel_trip("testville", booked.id)
    denied = rejected.model_copy(update={"id": "trip_denied_x", "status": TripStatus.denied})
    p.store.scope("testville").add(denied)
    for t in (rejected, booked, denied):
        with pytest.raises(ValueError):
            p.booking.cancel_trip("testville", t.id)
    assert p.store.scope("testville").get(type(denied), denied.id).status == TripStatus.denied


def test_cancel_while_vehicle_en_route_stays_cancelled_and_frees_capacity(testville):
    from roam.sim.world import SimWorld

    p, rt = testville
    p.clock.minute = 600
    r = _rider(p)
    t = p.booking.request_trip("testville", r.id, Mode.paratransit, A, B, SERVICE_DAY, 600)
    p.clock.today = SERVICE_DAY
    w = SimWorld(seed=1)
    adapters = p.build_adapters("testville", w)
    for a in adapters.values():
        a.params.no_show_rate = 0.0
    p.start_day("testville", SERVICE_DAY, adapters)
    while t.status != TripStatus.en_route:
        w.run_until(w.now + 1)
    p.clock.minute = w.now
    p.booking.cancel_trip("testville", t.id)
    w.run_until(26 * 60)
    assert t.status == TripStatus.cancelled and t.actual_pickup is None
    d = p.dispatcher("testville", SERVICE_DAY)
    assert all(t.id not in u.onboard for u in d.units)
