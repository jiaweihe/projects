"""Postgres persistence (Supabase in production). Runs against ROAM_TEST_DATABASE_URL; skipped without it."""

import os
import uuid
from pathlib import Path

import pytest

from roam.config.schema import config_from_dict
from roam.models import EligibilityStatus, Mode, Rider, TripRequest, TripStatus
from roam.platform import Platform

from .conftest import SERVICE_DAY, TODAY, new_city_config

DSN = os.environ.get("ROAM_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set ROAM_TEST_DATABASE_URL to a throwaway Postgres to run")
MIGRATION = Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "20261110000000_roam_records.sql"


@pytest.fixture
def db():
    import psycopg

    schema = "t_" + uuid.uuid4().hex[:10]  # isolated schema per test
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f"create schema {schema}")
        for role in ("anon", "authenticated"):  # Supabase roles, so the migration applies as-is
            conn.execute(f"do $$ begin create role {role}; exception when duplicate_object then null; end $$")
    dsn = f"{DSN}{'&' if '?' in DSN else '?'}options=-csearch_path%3D{schema}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(MIGRATION.read_text().replace("public.", ""))
    yield dsn
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f"drop schema {schema} cascade")


def _platform(dsn):
    from roam.persistence import PostgresStore

    p = Platform(today=TODAY)
    p.provision(config_from_dict(new_city_config()))
    store = PostgresStore(dsn)
    return p, store


def test_trips_survive_a_restart_and_the_day_plan_is_rebuilt(db):
    p, store = _platform(db)
    p.clock.minute = 600
    scope = p.store.scope("testville")
    pts = [(-75.08, 40.02), (-75.0, 40.08), (-75.06, 40.09), (-74.99, 40.01)]
    for k in range(6):
        scope.add(Rider(id=f"r{k}", tenant_id="testville", eligibility_status=EligibilityStatus.certified))
        p.booking.request_trip("testville", f"r{k}", Mode.paratransit, pts[k % 4], pts[(k + 1) % 4], SERVICE_DAY, 480 + 40 * k)
    cancelled = scope.list(TripRequest)[0]
    p.booking.cancel_trip("testville", cancelled.id)
    assert store.flush(p) == 12  # 6 riders + 6 trips
    assert store.flush(p) == 0  # nothing changed

    # "cold start": a brand-new process with the same config loads everything back
    p2, store2 = _platform(db)
    assert store2.load(p2) == 12
    trips = {t.id: t for t in p2.store.scope("testville").list(TripRequest)}
    assert trips[cancelled.id].status == TripStatus.cancelled
    booked = [t for t in trips.values() if t.status == TripStatus.booked]
    assert len(booked) == 5
    d = p2.dispatcher("testville", SERVICE_DAY)  # plan rebuilt from the database
    planned = {n.trip_id for u in d.units for n in u.route if n.trip_id}
    assert planned == {t.id for t in booked} and cancelled.id not in planned
    assert not [e for e in p2.ops.exceptions.values() if e.type == "replan_failed"]


def test_only_changed_records_are_written_and_tenants_stay_separate(db):
    p, store = _platform(db)
    other = new_city_config(id="othertown", name="Othertown", region={"state": "PA", "jurisdiction": "Othertown"})
    p.provision(config_from_dict(other))
    p.store.scope("testville").add(Rider(id="a", tenant_id="testville"))
    p.store.scope("othertown").add(Rider(id="b", tenant_id="othertown"))
    assert store.flush(p) == 2
    p.store.scope("testville").get(Rider, "a").contact["phone"] = "+1555"  # in-place mutation
    assert store.flush(p) == 1

    only_tv = Platform(today=TODAY)
    only_tv.provision(config_from_dict(new_city_config()))
    from roam.persistence import PostgresStore

    assert PostgresStore(db).load(only_tv) == 1  # a deployment only loads its own tenants
    assert only_tv.store.scope("testville").get(Rider, "a").contact["phone"] == "+1555"


def test_api_flushes_after_each_write(db):
    from fastapi.testclient import TestClient

    from roam.api import Principal, create_app

    p, store = _platform(db)
    c = TestClient(create_app(p, {"ops": Principal("ops", None, "s")}, realtime_clock=False, persistence=store))
    r = c.post("/tenants/testville/riders", json={"eligibility_status": "certified"}, headers={"X-Api-Key": "ops"})
    assert r.status_code == 201
    p2, store2 = _platform(db)
    assert store2.load(p2) == 1


def test_migration_blocks_supabase_public_roles(db):
    import psycopg

    with psycopg.connect(db, autocommit=True) as conn:
        assert conn.execute("select relrowsecurity from pg_class where relname = 'roam_records'").fetchone()[0] is True
        privs = conn.execute(
            "select count(*) from information_schema.role_table_grants where table_name = 'roam_records' "
            "and grantee in ('anon', 'authenticated')"
        ).fetchone()[0]
        assert privs == 0
