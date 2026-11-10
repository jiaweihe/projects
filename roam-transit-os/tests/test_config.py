import pytest

from roam.config.schema import config_from_dict, load_config
from roam.config.validate import validate
from roam.platform import ProvisioningError

from .conftest import FIXTURES, TENANTS, new_city_config


@pytest.mark.parametrize("name", FIXTURES)
def test_fixtures_validate(name):
    cfg, geoms = load_config(TENANTS / f"{name}.yaml")
    rep = validate(cfg, geoms)
    assert rep.ok, rep.errors


def test_mercer_go_live_blocked_on_moves_decision():
    cfg, geoms = load_config(TENANTS / "mercer_county_nj.yaml")
    rep = validate(cfg, geoms)
    assert not rep.can_go_live
    assert any("MOVES" in b for b in rep.golive_blockers)


def test_av_tenants_need_state_authorization():
    cfg, geoms = load_config(TENANTS / "austin_tx.yaml")
    assert any("state AV authorization" in b for b in validate(cfg, geoms).golive_blockers)


def test_jersey_city_is_excluded(platform):
    raw = new_city_config(id="jersey_city", name="Jersey City", region={"state": "NJ", "jurisdiction": "Jersey City"})
    rep = validate(*config_from_dict(raw))
    assert not rep.ok and any("excluded" in e for e in rep.errors)
    with pytest.raises(ProvisioningError):
        platform.provision(config_from_dict(raw))


def test_paratransit_requires_ada_rules():
    raw = new_city_config(ada_rules=None)
    assert any("ada_rules" in e for e in validate(*config_from_dict(raw)).errors)


def test_paratransit_fare_cap_two_times_fixed_route():
    raw = new_city_config(fares={"paratransit": {"base": 5.0}, "microtransit": {"base": 1.5}})
    assert any("exceeds" in e for e in validate(*config_from_dict(raw)).errors)


def test_missing_fare_and_zone_errors():
    raw = new_city_config(fares={"paratransit": {"base": 2.0}}, zones=[new_city_config()["zones"][0]])
    errs = validate(*config_from_dict(raw)).errors
    assert any("fares.microtransit" in e for e in errs)
    assert any("mode microtransit has no service zone" in e for e in errs)


def test_unclosed_polygon_rejected():
    bad = {"type": "Polygon", "coordinates": [[[-75.1, 40.0], [-74.9, 40.0], [-74.9, 40.1], [-75.1, 40.1]]]}
    raw = new_city_config(zones=[{"id": "z", "mode": "paratransit", "geometry": bad}, {"id": "m", "mode": "microtransit", "geometry": bad}])
    assert any("not closed" in e for e in validate(*config_from_dict(raw)).errors)


def test_av_fleet_needs_odd():
    raw = new_city_config()
    raw["fleet"].append({"adapter": "av_partner", "count": 1, "seats": 4, "wheelchair_positions": 0, "prefix": "AV"})
    assert any("odd_zone_ids" in e for e in validate(*config_from_dict(raw)).errors)


def test_shift_assignment_never_overlaps_on_a_vehicle():
    from datetime import date

    from roam.platform import Platform

    p = Platform()
    rt = p.provision(TENANTS / "miami_dade_fl.yaml")
    shifts = rt.shifts_for(date(2026, 11, 17))
    by_vehicle = {}
    for s in shifts:
        by_vehicle.setdefault(s.vehicle_id, []).append((s.start, s.end))
    for spans in by_vehicle.values():
        spans.sort()
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))
    assert all(s.driver_id is None for s in shifts if "MDCAV" in s.vehicle_id)


@pytest.mark.parametrize("bad", ["../evil", "Jersey City", "a/b", 'x"y', "", "A" * 80])
def test_tenant_id_is_a_safe_slug(bad):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        config_from_dict(new_city_config(id=bad))
