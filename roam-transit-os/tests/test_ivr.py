from roam.ivr import IVRSession, twiml
from roam.models import EligibilityStatus, Rider, TripRequest, TripStatus


def _setup(testville):
    p, rt = testville
    p.clock.minute = 600
    r = p.store.scope("testville").add(Rider(
        id="rider_0042", tenant_id="testville", eligibility_status=EligibilityStatus.certified,
        contact={"phone": "+15550001111"}, saved_places={"home": (-75.05, 40.06), "clinic": (-75.00, 40.03)},
    ))
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
    s = IVRSession(p, "testville", "+19999999999")
    assert "rider number" in s.start().say
    assert "To book" in s.handle("42#").say
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
