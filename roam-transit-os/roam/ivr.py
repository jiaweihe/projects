"""Phone / IVR booking (spec §5, §7.2, build step 7).

Phone is a first-class channel. A call is a small state machine that accepts keypad
(DTMF) or speech at every step. Speech is interpreted by a pluggable ``BookingAgent``
(rule-based by default; an LLM agent can be dropped in behind the same protocol).
Pressing 0, saying "agent", or two failed attempts transfers to a human and raises an
``ivr_human_fallback`` item in the operations console.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, Protocol
from xml.sax.saxutils import escape

from .models import Channel, Mode, Rider, TripRequest, TripStatus

if TYPE_CHECKING:
    from .platform import Platform


@dataclass
class IVRResponse:
    say: str
    gather: str = "dtmf speech"  # what input to collect next
    done: bool = False
    transfer: bool = False


class BookingAgent(Protocol):
    def interpret(self, state: str, text: str, ctx: dict[str, Any]) -> dict[str, Any]: ...


WORD_DIGITS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}


class RuleBasedAgent:
    """Deterministic speech interpretation good enough for the MVP flow."""

    def interpret(self, state: str, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
        t = text.lower().strip()
        if re.search(r"\b(agent|operator|human|representative|person)\b", t):
            return {"intent": "agent"}
        if state == "menu":
            if "cancel" in t:
                return {"choice": "2"}
            if "status" in t or "where" in t:
                return {"choice": "3"}
            if "book" in t or "ride" in t or "trip" in t:
                return {"choice": "1"}
        if state in ("pickup", "destination"):
            for i, name in enumerate(ctx.get("places", []), start=1):
                if name.lower() in t:
                    return {"choice": str(i)}
        if state == "date" and "tomorrow" in t:
            return {"choice": "1"}
        if state == "time":
            m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", t)
            if m:
                h, mi = int(m.group(1)), int(m.group(2) or 0)
                if m.group(3) and m.group(3).startswith("p") and h < 12:
                    h += 12
                return {"choice": f"{h:02d}{mi:02d}", "appointment": "appointment" in t or "be there" in t}
        if state == "confirm_cancel":
            if re.search(r"\b(no|keep|don'?t)\b", t):
                return {"choice": "2"}
            if re.search(r"\b(yes|yeah|cancel|confirm)\b", t):
                return {"choice": "1"}
        if state == "confirm":
            if re.search(r"\b(yes|yeah|confirm|correct|keep)\b", t):
                return {"choice": "1"}
            if re.search(r"\b(no|cancel)\b", t):
                return {"choice": "2"}
        digits = "".join(WORD_DIGITS.get(w, w) for w in re.findall(r"[a-z]+|\d", t) if w in WORD_DIGITS or w.isdigit())
        return {"choice": digits} if digits else {}


_PIN_ITERATIONS = 200_000


def set_pin(rider: Rider, pin: str) -> None:
    """Store a salted PBKDF2 hash of the rider's phone PIN (never the PIN itself)."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, _PIN_ITERATIONS)
    rider.contact.pop("pin", None)
    rider.contact["pin_hash"] = f"pbkdf2_sha256${_PIN_ITERATIONS}${salt.hex()}${digest.hex()}"


def check_pin(rider: Rider | None, pin: str) -> bool:
    stored = rider.contact.get("pin_hash", "") if rider else ""
    if not stored or not pin:
        return False
    try:
        _, iters, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), int(iters))
    except ValueError:  # corrupt record: fail closed
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def _next_occurrence(today: date, month: int, day: int) -> date | None:
    """The next date (after today) with this month/day within a year, or None."""
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d > today:
            return d
    return None


def _fmt(minutes: float) -> str:
    h, m = divmod(int(round(minutes)), 60)
    return f"{(h - 1) % 12 + 1}:{m:02d} {'AM' if h < 12 else 'PM'}"


@dataclass
class IVRSession:
    platform: Platform
    tenant_id: str
    caller: str
    agent: BookingAgent = field(default_factory=RuleBasedAgent)
    state: str = "greet"
    rider: Rider | None = None
    data: dict[str, Any] = field(default_factory=dict)
    failures: int = 0
    transcript: list[tuple[str, str]] = field(default_factory=list)

    def _places(self) -> list[str]:
        return list(self.rider.saved_places.keys()) if self.rider else []

    def _transfer(self, reason: str) -> IVRResponse:
        self.state = "transfer"
        self.platform.ops.raise_exception(
            type="ivr_human_fallback",
            severity=3,
            tenant_id=self.tenant_id,
            at=self.platform.clock.minute,
            service_date=self.platform.clock.today,
            message=f"caller {self.caller[-4:]}: {reason}",
        )
        return IVRResponse("Please hold while I connect you to a reservation agent.", gather="", done=True, transfer=True)

    def _retry(self, prompt: str) -> IVRResponse:
        self.failures += 1
        if self.failures >= 2:
            return self._transfer(f"input not understood at step {self.state}")
        return IVRResponse("Sorry, I didn't get that. " + prompt)

    def start(self) -> IVRResponse:
        scope = self.platform.store.scope(self.tenant_id)
        self.rider = next((r for r in scope.list(Rider) if r.contact.get("phone") == self.caller), None)
        name = self.platform.tenant(self.tenant_id).config.branding.display_name
        if self.rider is None:
            self.state = "identify"
            return IVRResponse(f"Welcome to {name}. Please enter your rider number followed by pound, or press 0 for an agent.")
        self.state = "menu"
        return IVRResponse(f"Welcome to {name}. {self._menu()}")

    @staticmethod
    def _menu() -> str:
        return "To book a ride press 1. To cancel your next ride press 2. To hear your ride status press 3. For an agent press 0."

    def handle(self, text: str) -> IVRResponse:
        self.transcript.append(("caller", "<PIN>" if self.state == "pin" else text))  # never log a PIN
        resp = self._handle(text.strip())
        self.transcript.append(("system", resp.say))
        return resp

    def _handle(self, text: str) -> IVRResponse:
        if self.state == "greet":
            return self.start()
        ctx = {"places": self._places()}
        parsed = {"choice": text.rstrip("#")} if re.fullmatch(r"[\d#*]+", text) else self.agent.interpret(self.state, text, ctx)
        if parsed.get("intent") == "agent" or parsed.get("choice") == "0":
            return self._transfer("caller requested an agent")
        choice = parsed.get("choice", "")
        scope = self.platform.store.scope(self.tenant_id)

        if self.state == "identify":
            rid = next((r for r in scope.list(Rider) if r.id.split("_")[-1].lstrip("0") == choice.lstrip("0")), None)
            # always ask for a PIN, even for unknown numbers or riders without one, so the
            # prompts never reveal which rider numbers exist; a rider number alone is not identity
            self.data["candidate"], self.state, self.failures = rid, "pin", 0
            return IVRResponse("Please enter your four digit PIN followed by pound.")

        if self.state == "pin":
            cand: Rider | None = self.data["candidate"]
            if not check_pin(cand, choice):
                return self._retry("Please enter your PIN followed by pound.")
            self.rider, self.state, self.failures = cand, "menu", 0
            del self.data["candidate"]
            return IVRResponse(self._menu())

        if self.state == "menu":
            if choice == "1":
                if not self._places():
                    return self._transfer("rider has no saved places")
                self.state, self.failures = "pickup", 0
                return IVRResponse("Where should we pick you up? " + self._place_prompt())
            if choice == "2":
                upcoming = self._upcoming()
                if not upcoming:
                    return IVRResponse("You have no upcoming rides. " + self._menu())
                t = upcoming[0]
                self.data["cancel_trip_id"], self.state, self.failures = t.id, "confirm_cancel", 0
                return IVRResponse(
                    f"Your next ride is {t.service_date:%A} at {_fmt(t.negotiated_pickup or t.requested_time)}. "
                    "To cancel it press 1. To keep it press 2."
                )
            if choice == "3":
                upcoming = self._upcoming()
                if not upcoming:
                    return IVRResponse("You have no upcoming rides. " + self._menu())
                t = upcoming[0]
                w = t.window or (t.requested_time, t.requested_time + 30)
                return IVRResponse(f"Your next ride is {t.service_date:%A}, pickup between {_fmt(w[0])} and {_fmt(w[1])}. " + self._menu())
            return self._retry(self._menu())

        if self.state == "confirm_cancel":
            if choice not in ("1", "2"):
                return self._retry("To cancel the ride press 1. To keep it press 2.")
            trip_id = self.data.pop("cancel_trip_id")
            self.state, self.failures = "menu", 0
            if choice == "2":
                return IVRResponse("Your ride is kept. " + self._menu())
            try:
                self.platform.booking.cancel_trip(self.tenant_id, trip_id, "cancelled by phone")
            except ValueError:  # changed meanwhile (cancelled in the app, already served...)
                return IVRResponse("That ride can no longer be cancelled. " + self._menu())
            return IVRResponse("Your ride is cancelled. " + self._menu())

        if self.state in ("pickup", "destination"):
            places = self._places()
            if not choice.isdigit() or not (1 <= int(choice) <= len(places)):
                return self._retry(self._place_prompt())
            self.data[self.state] = places[int(choice) - 1]
            self.failures = 0
            if self.state == "pickup":
                self.state = "destination"
                return IVRResponse("Where are you going? " + self._place_prompt(exclude=self.data["pickup"]))
            if self.data["destination"] == self.data["pickup"]:
                return self._retry("Pickup and destination must differ. " + self._place_prompt())
            self.state = "date"
            return IVRResponse("For tomorrow press 1, or enter the date as month and day, four digits.")

        if self.state == "date":
            today = self.platform.clock.today
            d: date | None
            if choice == "1":
                d = today + timedelta(days=1)
            elif re.fullmatch(r"\d{4}", choice):
                d = _next_occurrence(today, int(choice[:2]), int(choice[2:]))
                if d is None:  # impossible date, or Feb 29 with no leap year next
                    return self._retry("Enter the date as four digits, month then day.")
            else:
                return self._retry("For tomorrow press 1, or enter four digits for month and day.")
            self.data["date"], self.state, self.failures = d, "time", 0
            return IVRResponse(
                "Enter your pickup time as four digits in 24-hour time, for example 0 9 3 0. "
                "If this is an appointment time, say 'appointment' and the time."
            )

        if self.state == "time":
            if not re.fullmatch(r"\d{3,4}", choice):
                return self._retry("Enter the time as four digits, for example 0 9 3 0.")
            choice = choice.zfill(4)
            h, m = int(choice[:2]), int(choice[2:])
            if h > 23 or m > 59:
                return self._retry("Enter the time as four digits, for example 0 9 3 0.")
            self.data["time"] = h * 60 + m
            self.data["time_type"] = "appointment" if parsed.get("appointment") else "pickup"
            rider = self.rider
            assert rider is not None
            trip = self.platform.booking.request_trip(
                self.tenant_id,
                rider.id,
                Mode.paratransit
                if rider.eligibility_status.value in ("certified", "conditional", "temporary")
                and Mode.paratransit in self.platform.tenant(self.tenant_id).config.modes
                else Mode.microtransit,
                rider.saved_places[self.data["pickup"]],
                rider.saved_places[self.data["destination"]],
                self.data["date"],
                self.data["time"],
                Channel.ivr,
                self.data["time_type"],
            )
            self.data["trip_id"] = trip.id
            if trip.status != TripStatus.booked:
                self.state = "menu"
                return IVRResponse(
                    f"Sorry, I couldn't book that ride: {trip.status_reason}. Press 0 for an agent, or " + self._menu().lower()
                )
            # every booked trip carries its promised window; fall back defensively (asserts vanish under -O)
            w = trip.window or (trip.requested_time, trip.requested_time + 30)
            self.state, self.failures = "confirm", 0
            return IVRResponse(
                f"I can pick you up on {trip.service_date:%A %B %d} between {_fmt(w[0])} and {_fmt(w[1])}"
                f"{' (adjusted from your requested time)' if trip.status_reason else ''}. "
                f"The fare is ${trip.fare:.2f}. To confirm press 1. To cancel press 2."
            )

        if self.state == "confirm":
            if choice == "1":
                self.state = "done"
                return IVRResponse("Your ride is booked. We will text you when your driver is on the way. Goodbye.", gather="", done=True)
            if choice == "2":
                self.platform.booking.cancel_trip(self.tenant_id, self.data["trip_id"], "declined offered time by phone")
                self.state = "menu"
                return IVRResponse("The ride was not booked. " + self._menu())
            return self._retry("To confirm press 1. To cancel press 2.")
        return IVRResponse("Goodbye.", gather="", done=True)

    def _place_prompt(self, exclude: str | None = None) -> str:
        return " ".join(f"For {p} press {i}." for i, p in enumerate(self._places(), start=1) if p != exclude)

    def _upcoming(self) -> list[TripRequest]:
        assert self.rider is not None
        today = self.platform.clock.today
        trips = [
            t
            for t in self.platform.store.scope(self.tenant_id).list(TripRequest, rider_id=self.rider.id)
            if t.status in (TripStatus.booked, TripStatus.scheduled) and t.service_date >= today
        ]
        return sorted(trips, key=lambda t: (t.service_date, t.negotiated_pickup or t.requested_time))


def twiml(resp: IVRResponse, action_url: str, transfer_number: str | None = None) -> str:
    """Render an IVRResponse as Twilio TwiML (Gather -> Say, or Dial for human fallback)."""
    say = f"<Say>{escape(resp.say)}</Say>"
    if resp.transfer:
        dial = f"<Dial>{escape(transfer_number)}</Dial>" if transfer_number else ""
        return f'<?xml version="1.0" encoding="UTF-8"?><Response>{say}{dial}</Response>'
    if resp.done:
        return f'<?xml version="1.0" encoding="UTF-8"?><Response>{say}<Hangup/></Response>'
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><Response><Gather input="{resp.gather}" action="{escape(action_url)}" '
        f'method="POST" timeout="6" finishOnKey="#" speechTimeout="auto">{say}</Gather>'
        f'<Redirect method="POST">{escape(action_url)}</Redirect></Response>'
    )
