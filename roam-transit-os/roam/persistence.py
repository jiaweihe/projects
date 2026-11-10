"""Postgres persistence (Supabase or any Postgres) for operational records.

Tenant configuration comes from the YAML files in ``tenants/`` (versioned in git); what
must survive a restart is what happens at runtime: riders, standing orders, trips,
events, incidents, complaints and invoices. Those are stored as JSONB rows in one table,
``roam_records`` (see ``supabase/migrations``), keyed by (kind, id) with ``tenant_id``
as a column so Postgres row-level security can isolate tenants.

Records are mutated in place by the services (a trip's status changes after it is
stored), so writes are not hooked per call. Instead :meth:`PostgresStore.flush` saves
every record whose JSON changed since the last flush; the API calls it after each
request. Requires ``pip install -e .[supabase]`` (psycopg 3).
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from pydantic import BaseModel

from . import models as M

if TYPE_CHECKING:
    from .platform import Platform

PERSISTED: dict[str, type[BaseModel]] = {
    cls.__name__: cls for cls in (M.Rider, M.StandingOrder, M.TripRequest, M.Event, M.Incident, M.Complaint, M.Invoice)
}

SCHEMA_SQL = """
create table if not exists roam_records (
  kind       text        not null,
  id         text        not null,
  tenant_id  text        not null,
  data       jsonb       not null,
  updated_at timestamptz not null default now(),
  primary key (kind, id)
);
create index if not exists roam_records_tenant_kind on roam_records (tenant_id, kind);
alter table roam_records enable row level security;
"""


class PostgresStore:
    def __init__(self, dsn: str):
        import psycopg  # optional dependency: pip install -e .[supabase]

        self._psycopg = psycopg
        self.dsn = dsn
        self._seen: dict[tuple[str, str], str] = {}  # (kind, id) -> hash of last saved JSON

    def _connect(self):
        # prepare_threshold=None: works through Supabase's transaction pooler (PgBouncer)
        return self._psycopg.connect(self.dsn, autocommit=False, prepare_threshold=None)

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(SCHEMA_SQL)

    def load(self, platform: Platform) -> int:
        """Hydrate the in-memory store with persisted records of the provisioned tenants."""
        tenants = list(platform.store.tenants)
        if not tenants:
            return 0
        n = 0
        with self._connect() as conn:
            rows = conn.execute(
                "select kind, data from roam_records where tenant_id = any(%s) and kind = any(%s) order by updated_at",
                (tenants, list(PERSISTED)),
            ).fetchall()
        for kind, data in rows:
            rec = PERSISTED[kind].model_validate(data)
            platform.store._put(rec)
            self._seen[(kind, rec.id)] = _digest(data)  # type: ignore[attr-defined]
            n += 1
        return n

    def flush(self, platform: Platform) -> int:
        """Upsert every persisted record that changed since the last flush. Returns rows written."""
        batch = []
        for kind in PERSISTED:
            for rec in platform.store._tables.get(kind, {}).values():
                data = rec.model_dump(mode="json")
                h = _digest(data)
                key = (kind, rec.id)  # type: ignore[attr-defined]
                if self._seen.get(key) != h:
                    batch.append((kind, rec.id, rec.tenant_id, json.dumps(data), key, h))  # type: ignore[attr-defined]
        if not batch:
            return 0
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(
                "insert into roam_records (kind, id, tenant_id, data, updated_at) values (%s, %s, %s, %s::jsonb, now()) "
                "on conflict (kind, id) do update set data = excluded.data, tenant_id = excluded.tenant_id, updated_at = now()",
                [row[:4] for row in batch],
            )
        for *_, key, h in batch:
            self._seen[key] = h
        return len(batch)


def _digest(data: dict) -> str:
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
