import pytest

from roam.models import Rider, TripRequest
from roam.store import TenantIsolationError

from .conftest import TENANTS


def test_tenant_scope_isolation(testville):
    p, rt = testville
    p.provision(TENANTS / "austin_tx.yaml")
    r = p.store.scope("testville").add(Rider(id="rider_x", tenant_id="testville"))
    with pytest.raises(KeyError):
        p.store.scope("austin_tx").get(Rider, r.id)
    with pytest.raises(TenantIsolationError):
        p.store.scope("austin_tx").add(Rider(id="rider_y", tenant_id="testville"))
    assert p.store.scope("austin_tx").list(Rider) == []


def test_ops_scope_sees_only_assigned_tenants(testville):
    p, rt = testville
    p.provision(TENANTS / "austin_tx.yaml")
    seat = p.store.ops_scope({"testville"})
    assert {v.tenant_id for v in seat.list(type(rt.vehicles[0]))} == {"testville"}
    with pytest.raises(TenantIsolationError):
        seat.tenant("austin_tx")
    assert {v.tenant_id for v in p.store.ops_scope().list(type(rt.vehicles[0]))} == {"testville", "austin_tx"}
