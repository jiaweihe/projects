"""Vercel entrypoint (Python runtime): exposes the FastAPI ``app``.

Configuration comes from environment variables (set them in the Vercel project settings):

    ROAM_API_KEYS      JSON: {"<key>": {"role": "ops", "tenant_ids": null, "seat_id": "seat-1"}, ...}
    DATABASE_URL       Supabase Postgres connection string (transaction pooler, port 6543)
    ROAM_TENANTS       comma-separated tenant files in tenants/ (default: the three pilot fixtures)
    TWILIO_AUTH_TOKEN  enables the IVR webhook (closed without it)
    ROAM_PUBLIC_URL    the public https URL Twilio calls (signature check)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from roam.api import Principal, create_app  # noqa: E402
from roam.persistence import PostgresStore  # noqa: E402
from roam.platform import Platform  # noqa: E402

DEFAULT_TENANTS = "mercer_county_nj,austin_tx,miami_dade_fl"


def _keys() -> dict[str, Principal]:
    out: dict[str, Principal] = {}
    for key, spec in json.loads(os.environ.get("ROAM_API_KEYS", "{}")).items():
        out[key] = Principal(
            role=spec["role"],
            tenant_ids=set(spec["tenant_ids"]) if spec.get("tenant_ids") is not None else None,
            seat_id=spec.get("seat_id"),
            vehicle_ids=set(spec["vehicle_ids"]) if spec.get("vehicle_ids") else None,
            rider_id=spec.get("rider_id"),
        )
    return out


def build_app():
    platform = Platform()
    tenants = [t.strip() for t in os.environ.get("ROAM_TENANTS", DEFAULT_TENANTS).split(",") if t.strip()]
    for t in tenants:
        platform.provision(ROOT / "tenants" / f"{t}.yaml")
    platform.ops.add_seat("seat-1", "Ops seat 1", set(tenants))
    store = None
    if os.environ.get("DATABASE_URL"):
        store = PostgresStore(os.environ["DATABASE_URL"])
        store.load(platform)  # riders, trips, events... survive cold starts
    return create_app(
        platform,
        _keys(),
        twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN"),
        public_base_url=os.environ.get("ROAM_PUBLIC_URL"),
        persistence=store,
    )


app = build_app()
