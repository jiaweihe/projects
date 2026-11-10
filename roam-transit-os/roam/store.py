"""Multi-tenant in-memory store.

The production target is PostgreSQL + PostGIS with row-level security on ``tenant_id``
(see ``db/schema.sql``). This store enforces the same contract in-process:

* a :class:`TenantScope` can only read and write rows of its own tenant and stamps
  ``tenant_id`` on insert;
* only an :class:`OpsScope` (a Roam operations seat) may read across tenants.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class TenantIsolationError(PermissionError):
    pass


class Store:
    def __init__(self) -> None:
        # table name -> id -> record
        self._tables: dict[str, dict[str, BaseModel]] = defaultdict(dict)
        self.tenants: dict[str, Any] = {}  # tenant_id -> TenantRuntime (see tenancy.py)

    # raw access is private to the package; callers use scopes
    def _put(self, rec: BaseModel) -> None:
        self._tables[type(rec).__name__][rec.id] = rec  # type: ignore[attr-defined]

    def _all(self, cls: type[T]) -> Iterable[T]:
        return self._tables[cls.__name__].values()  # type: ignore[return-value]

    def scope(self, tenant_id: str) -> "TenantScope":
        if tenant_id not in self.tenants:
            raise KeyError(f"unknown tenant {tenant_id}")
        return TenantScope(self, tenant_id)

    def ops_scope(self, tenant_ids: Iterable[str] | None = None) -> "OpsScope":
        return OpsScope(self, set(tenant_ids) if tenant_ids is not None else None)


class TenantScope:
    def __init__(self, store: Store, tenant_id: str):
        self._s = store
        self.tenant_id = tenant_id

    def add(self, rec: T) -> T:
        tid = getattr(rec, "tenant_id", None)
        if tid is None:
            raise TenantIsolationError(f"{type(rec).__name__} has no tenant_id")
        if tid != self.tenant_id:
            raise TenantIsolationError(f"cannot write {tid} record from {self.tenant_id} scope")
        self._s._put(rec)
        return rec

    def get(self, cls: type[T], rec_id: str) -> T:
        rec = self._s._tables[cls.__name__].get(rec_id)
        if rec is None or getattr(rec, "tenant_id", None) != self.tenant_id:
            raise KeyError(f"{cls.__name__} {rec_id} not found")  # never leak existence across tenants
        return rec  # type: ignore[return-value]

    def list(self, cls: type[T], **filters: Any) -> list[T]:
        out = []
        for r in self._s._all(cls):
            if getattr(r, "tenant_id", None) != self.tenant_id:
                continue
            if all(getattr(r, k) == v for k, v in filters.items()):
                out.append(r)
        return out

    def delete(self, cls: type[T], rec_id: str) -> None:
        self.get(cls, rec_id)
        del self._s._tables[cls.__name__][rec_id]


class OpsScope:
    """Cross-tenant read access for a Roam operations seat (optionally limited to a tenant set)."""

    def __init__(self, store: Store, tenant_ids: set[str] | None):
        self._s = store
        self.tenant_ids = tenant_ids

    def _visible(self, tid: str | None) -> bool:
        return tid is not None and (self.tenant_ids is None or tid in self.tenant_ids)

    def list(self, cls: type[T], **filters: Any) -> list[T]:
        return [
            r
            for r in self._s._all(cls)
            if self._visible(getattr(r, "tenant_id", None)) and all(getattr(r, k) == v for k, v in filters.items())
        ]

    def tenant(self, tenant_id: str) -> TenantScope:
        if not self._visible(tenant_id):
            raise TenantIsolationError(f"seat not assigned to {tenant_id}")
        return self._s.scope(tenant_id)
