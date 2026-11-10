from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TENANTS = ROOT / "tenants"
FIXTURES = ["mercer_county_nj", "austin_tx", "miami_dade_fl"]
TODAY = date(2026, 11, 16)  # Monday
SERVICE_DAY = date(2026, 11, 17)  # Tuesday

SQUARE = {  # ~11 x 11 km test zone (fictional "Testville")
    "type": "Polygon",
    "coordinates": [[[-75.10, 40.00], [-74.97, 40.00], [-74.97, 40.10], [-75.10, 40.10], [-75.10, 40.00]]],
}


def new_city_config(**over) -> dict:
    """A brand-new tenant described only by config (plug-and-play test)."""
    wk = ["06:00", "21:00"]
    cfg = {
        "id": "testville",
        "name": "Testville",
        "type": "city",
        "region": {"state": "PA", "jurisdiction": "Testville"},
        "phase": 1,
        "modes": ["paratransit", "microtransit"],
        "zones": [
            {"id": "tv_para", "mode": "paratransit", "geometry": SQUARE},
            {"id": "tv_micro", "mode": "microtransit", "geometry": SQUARE},
        ],
        "service_hours": {"mon": wk, "tue": wk, "wed": wk, "thu": wk, "fri": wk, "sat": None, "sun": None},
        "fares": {"paratransit": {"base": 2.0}, "microtransit": {"base": 1.5}},
        "booking_rules": {"paratransit": {}, "microtransit": {"max_wait_min": 30}},
        "ada_rules": {"fixed_route_fare": 1.25},
        "fleet": [{"adapter": "human_driver", "count": 4, "seats": 8, "wheelchair_positions": 1, "prefix": "TV"}],
        "shifts": [{"start": "05:30", "end": "14:00", "count": 4}, {"start": "14:00", "end": "22:00", "count": 3}],
        "depot": [-75.03, 40.05],
        "funding_sources": [{"id": "general", "type": "city"}],
        "branding": {"display_name": "Testville On Demand"},
        "contacts": {"city_program_manager": "pm@testville.example", "insurer": "claims@pool.example"},
        "road_network_bbox": [-75.2, 39.9, -74.9, 40.2],
    }
    cfg = copy.deepcopy(cfg)
    cfg.update(over)
    return cfg


@pytest.fixture
def platform():
    from roam.platform import Platform

    return Platform(today=TODAY)


@pytest.fixture
def testville(platform):
    from roam.config.schema import config_from_dict

    rt = platform.provision(config_from_dict(new_city_config()))
    return platform, rt
