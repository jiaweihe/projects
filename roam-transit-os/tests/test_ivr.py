from roam.ivr import IVRSession, twiml
from roam.models import EligibilityStatus, Rider, TripRequest, TripStatus


def _setup(testville):
    p, rt = testville
    p.clock.minute = 600
    r = p.store.scope("testville").add(
        Rider(
            id="rider_0042",
            tenant_id="testville",
            eligibility_status=EligibilityStatus.certified,
            contact={"phone": "+15550001111"},
            saved_places={"home": (-75.05, 40.06), "clinic": (-75.00, 40.03)},
        )
    )
    return p, r


def test_keypad_booking_call(testville):
    p, r = _setup(testville)
    s = IVRSession(p, "testville", "+15550001111")
    assert "To book a ride press 1" in s.start().say
    assert "pick you up" in s.handle("1").say
    assert "Where are you going" in s.handle("1").say  # home
    assert "tomorrow" in s.handle("2").say  # clinic
    assert "four digits" in s.handle("1").say  # tomorrow
    offer = s.handle("0930")
    assert "between" in offer.say and "confirm" in offer.say
    done = s.handle("1")
    assert done.done
    trip = p.store.scope("testville").get(TripRequest, s.data["trip_id"])
    assert trip.channel.value == "ivr" and trip.status == TripStatus.booked


def test_speech_and_unknown_caller(testville):
    p, r = _setup(testville)
    r.contact["pin"] = "2468"
    s = IVRSession(p, "testville", "+19999999999")
    assert "rider number" in s.start().say
    s.handle("42#")
    assert "To book" in s.handle("2468#").say
    s.handle("I want to book a ride")
    s.handle("from home")
    s.handle("to the clinic")
    s.handle("tomorrow please")
    offer = s.handle("appointment at 10:30 am")
    assert "between" in offer.say
    assert s.data["time_type"] == "appointment"


def test_human_fallback_raises_ops_item(testville):
    p, r = _setup(testville)
    s = IVRSession(p, "testville", "+15550001111")
    s.start()
    s.handle("9")
    resp = s.handle("blah")
    assert resp.transfer
    assert any(e.type == "ivr_human_fallback" for e in p.ops.exceptions.values())
    xml = twiml(resp, "https://x/ivr", "+15551234567")
    assert "<Dial>+15551234567</Dial>" in xml


def test_unknown_caller_needs_rider_number_and_pin(testville):
    p, r = _setup(testville)
    r.contact["pin"] = "2468"
    s = IVRSession(p, "testville", "+19999999999")
    s.start()
    assert "PIN" in s.handle("42#").say
    assert "PIN" in s.handle("1111#").say  # wrong PIN: retry
    assert s.handle("1357#").transfer  # second failure: hand to a human, never into the account
    s2 = IVRSession(p, "testville", "+19999999999")
    s2.start()
    s2.handle("42#")
    assert "To book" in s2.handle("2468#").say


def test_rider_without_pin_cannot_be_reached_by_number(testville):
    p, r = _setup(testville)  # no PIN on file
    s = IVRSession(p, "testville", "+19999999999")
    s.start()
    assert "PIN" in s.handle("42#").say
    s.handle("1111#")  # any PIN fails: there is none on file
    assert s.handle("2222#").transfer and s.rider is None  # agent verifies identity instead


def test_rider_numbers_cannot_be_enumerated_and_pin_never_logged(testville):
    p, r = _setup(testville)
    r.contact["pin"] = "2468"
    known, unknown = IVRSession(p, "testville", "+1999"), IVRSession(p, "testville", "+1999")
    known.start(), unknown.start()
    assert known.handle("42#").say == unknown.handle("777#").say  # same prompt whether or not the rider exists
    assert known.handle("9999#").say == unknown.handle("9999#").say
    ok = IVRSession(p, "testville", "+1999")
    ok.start(), ok.handle("42#"), ok.handle("2468#")
    assert "2468" not in repr(ok.transcript)


def _booked(p, r):
    from .conftest import SERVICE_DAY

    return p.booking.request_trip(
        "testville",
        r.id,
        __import__("roam.models", fromlist=["Mode"]).Mode.paratransit,
        r.saved_places["home"],
        r.saved_places["clinic"],
        SERVICE_DAY,
        600,
    )


def test_phone_cancel_requires_confirmation(testville):
    p, r = _setup(testville)
    t = _booked(p, r)
    s = IVRSession(p, "testville", "+15550001111")
    s.start()
    prompt = s.handle("2")
    assert "press 1" in prompt.say.lower() and t.status == TripStatus.booked  # nothing cancelled yet
    s.handle("2")  # "no, keep it"
    assert t.status == TripStatus.booked
    s.handle("2")
    s.handle("1")  # confirm
    assert t.status == TripStatus.cancelled


def test_leap_day_date_entry_does_not_crash(testville):
    from datetime import date

    p, r = _setup(testville)
    p.clock.today = date(2028, 3, 1)  # day after a leap day; next Feb 29 is in 2032
    s = IVRSession(p, "testville", "+15550001111")
    s.start(), s.handle("1"), s.handle("1"), s.handle("2")
    resp = s.handle("0229")
    assert not resp.done and "date" in resp.say.lower()


def test_cancel_confirmation_by_speech_and_race_with_other_channel(testville):
    p, r = _setup(testville)
    t = _booked(p, r)
    s = IVRSession(p, "testville", "+15550001111")
    s.start(), s.handle("cancel my ride")
    assert "Your ride is kept" in s.handle("no keep it").say and t.status == TripStatus.booked
    s.handle("cancel my ride")
    p.booking.cancel_trip("testville", t.id, "cancelled in the app meanwhile")
    resp = s.handle("yes cancel it")
    assert not resp.transfer and "no longer" in resp.say
