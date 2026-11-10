"""Synthetic demand (spec §13 step 2): riders and trip requests for a tenant and day."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date

from .. import geo
from ..models import AccessibilityNeed, EligibilityStatus, LonLat, Mode, Rider, new_id

# hourly weights (index = hour of day)
PARATRANSIT_PROFILE = [0, 0, 0, 0, 0, 0, 2, 6, 9, 8, 6, 5, 5, 6, 7, 7, 6, 4, 3, 2, 1, 1, 0, 0]
MICROTRANSIT_PROFILE = [0, 0, 0, 0, 0, 1, 3, 8, 9, 6, 4, 4, 5, 5, 5, 6, 8, 9, 7, 5, 3, 2, 1, 0]


@dataclass
class DemandSpec:
    paratransit_trips: int = 0
    microtransit_trips: int = 0
    av_trips: int = 0
    wheelchair_share: float = 0.20
    attractors: int = 8
    attractor_share: float = 0.6
    appointment_share: float = 0.25
    riders_per_trip: float = 0.5  # paratransit riders take ~2 trips/day (out + back)
    trip_length_scale_km: float = 5.0  # distance decay: P(dest) ~ exp(-d / scale)


@dataclass
class DemandItem:
    mode: Mode
    rider_id: str
    origin: LonLat
    destination: LonLat
    time: float  # requested pickup / appointment (minutes)
    time_type: str = "pickup"
    request_at: float | None = None  # when the request is made (real-time modes)


@dataclass
class Demand:
    riders: list[Rider] = field(default_factory=list)
    items: list[DemandItem] = field(default_factory=list)


def _sample_hour(profile: list[int], lo: float, hi: float, rng: random.Random) -> float:
    hours = [h for h in range(24) if lo <= h * 60 + 30 <= hi and profile[h] > 0]
    if not hours:
        return rng.uniform(lo, hi)
    h = rng.choices(hours, weights=[profile[x] for x in hours])[0]
    return min(hi, max(lo, h * 60 + rng.uniform(0, 60)))


def generate(rt, service_date: date, spec: DemandSpec, seed: int = 1) -> Demand:
    rng = random.Random(f"{rt.id}:{service_date}:{seed}")
    hours = rt.config.hours_for(service_date.weekday())
    if hours is None:
        return Demand()
    open_, close = hours
    out = Demand()

    def pick_dest(o: LonLat, sample) -> LonLat:
        cands = []
        for _ in range(30):
            d = sample()
            km = geo.haversine_km(o, d)
            if km >= 0.8:
                cands.append((d, km))
        if not cands:
            return sample()
        w = [math.exp(-km / spec.trip_length_scale_km) for _, km in cands]
        return rng.choices([c for c, _ in cands], weights=w)[0]

    def zone_sampler(mode: Mode):
        zones = rt.zones_for(mode)
        if not zones:
            return None
        g = zones[0].geometry
        attractors = [geo.random_point_in(g, rng) for _ in range(spec.attractors)]

        def sample() -> LonLat:
            if rng.random() < spec.attractor_share:
                for _ in range(20):
                    p = geo.jitter_point(rng.choice(attractors), 0.6, rng)
                    if geo.point_in_geometry(p, g):
                        return p
            return geo.random_point_in(g, rng)

        return sample

    # ---- paratransit: certified riders, mostly round trips, booked the day before
    if spec.paratransit_trips and Mode.paratransit in rt.config.modes:
        sample = zone_sampler(Mode.paratransit)
        n_riders = max(1, int(spec.paratransit_trips * spec.riders_per_trip))
        riders = []
        for _ in range(n_riders):
            needs = [AccessibilityNeed.wheelchair] if rng.random() < spec.wheelchair_share else []
            if not needs and rng.random() < 0.3:
                needs = [AccessibilityNeed.ambulatory_assist]
            r = Rider(
                id=new_id("rider"), tenant_id=rt.id, accessibility_needs=needs,
                eligibility_status=EligibilityStatus.certified, contact={"phone": f"+1555{rng.randrange(10**6, 10**7)}"},
            )
            r.saved_places["home"] = sample()  # type: ignore[misc]
            riders.append(r)
        out.riders.extend(riders)
        made = 0
        while made < spec.paratransit_trips:
            r = rng.choice(riders)
            home = r.saved_places["home"]
            dest = pick_dest(home, sample)
            t_out = _sample_hour(PARATRANSIT_PROFILE, open_ + 20, close - 240, rng)
            appt = rng.random() < spec.appointment_share
            out.items.append(DemandItem(Mode.paratransit, r.id, home, dest, t_out + (40 if appt else 0), "appointment" if appt else "pickup"))
            made += 1
            if made < spec.paratransit_trips:
                t_back = min(close - 20, t_out + rng.uniform(120, 300))
                out.items.append(DemandItem(Mode.paratransit, r.id, dest, home, t_back, "pickup"))
                made += 1

    # ---- microtransit / AV network: general public, real-time
    for mode, n in ((Mode.microtransit, spec.microtransit_trips), (Mode.av_network, spec.av_trips)):
        if not n or mode not in rt.config.modes:
            continue
        sample = zone_sampler(mode)
        for _ in range(n):
            r = Rider(id=new_id("rider"), tenant_id=rt.id,
                      accessibility_needs=[AccessibilityNeed.wheelchair] if rng.random() < 0.03 else [])
            out.riders.append(r)
            o = sample()  # type: ignore[misc]
            d = pick_dest(o, sample)
            t = _sample_hour(MICROTRANSIT_PROFILE, open_ + 5, close - 30, rng)
            out.items.append(DemandItem(mode, r.id, o, d, t, "pickup", request_at=t))
    return out
