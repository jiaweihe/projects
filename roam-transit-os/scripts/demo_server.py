"""Local preview: provision the 3 fixtures, simulate one service day, serve API + ops console.

    python scripts/demo_server.py            # http://127.0.0.1:8000  (API key: demo)
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import uvicorn

from roam.api import Principal, create_app
from roam.platform import Platform
from roam.sim.demand import DemandSpec
from roam.sim.runner import simulate_day

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ["mercer_county_nj", "austin_tx", "miami_dade_fl"]


def build() -> Platform:
    day = date.today() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    p = Platform(today=day - timedelta(days=1))
    for f in FIXTURES:
        p.provision(ROOT / "tenants" / f"{f}.yaml")
    p.ops.add_seat("seat-1", "Ops seat 1", set(FIXTURES))
    simulate_day(
        p,
        day,
        {
            "mercer_county_nj": DemandSpec(paratransit_trips=60, microtransit_trips=40),
            "austin_tx": DemandSpec(microtransit_trips=60, av_trips=20),
            "miami_dade_fl": DemandSpec(paratransit_trips=80, av_trips=20),
        },
        seed=7,
    )
    return p


if __name__ == "__main__":
    keys = {os.environ.get("ROAM_DEMO_KEY", "demo"): Principal("ops", None, "seat-1")}
    uvicorn.run(create_app(build(), keys, realtime_clock=False), host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
