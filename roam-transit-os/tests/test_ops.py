import pytest
from fastapi.testclient import TestClient

from roam.api import Principal, create_app
from roam.models import Incident, Severity
from roam.ops.console import OpsCenter
from roam.ops.incidents import LogNotifier, close_incident, open_incident

OPS = {"X-Api-Key": "ops"}


def test_incident_notification_rules(testville):
    p, rt = testville
    scope = p.store.scope("testville")
    contacts = {"city_program_manager": "pm@x", "insurer": "claims@x"}  # police_fire deliberately missing
    n = LogNotifier()
    minor = open_incident(scope, contacts, n, severity=Severity.low, summary="mirror clipped")
    assert [x["role"] for x in minor.notifications] == ["city_program_manager"] and minor.status == "notified"
    serious = open_incident(scope, contacts, n, severity=Severity.high, summary="collision, no injuries")
    assert [x["role"] for x in serious.notifications] == ["city_program_manager", "insurer"]
    injury = open_incident(scope, contacts, n, severity=Severity.medium, summary="rider fell", injuries=True, parties=["rider"])
    roles = [x["role"] for x in injury.notifications]
    assert roles == ["city_program_manager", "insurer", "police_fire"]
    assert injury.notifications[-1]["delivered"] is False  # never silently "sent" to nobody
    assert all(x["delivered"] for x in injury.notifications[:-1])
    assert len(n.sent) == 5  # undeliverable notice is recorded, not sent
    closed = close_incident(scope, injury.id, "wet floor", "added non-slip mats")
    assert closed.status == "closed" and "Root cause: wet floor" in closed.close_out
    assert "Notified: city_program_manager, insurer\n" in closed.close_out
    assert "Not delivered (no contact): police_fire" in closed.close_out


def test_incident_api_is_tenant_scoped(testville):
    p, rt = testville
    c = TestClient(create_app(p, {"ops": Principal("ops", None, "s"), "city": Principal("city", {"testville"})}, realtime_clock=False))
    r = c.post("/tenants/testville/incidents", json={"summary": "minor", "severity": 4}, headers=OPS)
    assert r.status_code == 201
    inc_id = r.json()["id"]
    assert c.post("/tenants/testville/incidents", json={"summary": "x"}, headers={"X-Api-Key": "city"}).status_code == 403
    r = c.post(f"/tenants/testville/incidents/{inc_id}/close", params={"root_cause": "a", "corrective_action": "b"}, headers=OPS)
    assert r.json()["status"] == "closed"
    assert p.store.scope("testville").get(Incident, inc_id).status == "closed"


def test_undeliverable_incident_notice_alerts_ops(testville):
    p, rt = testville
    rt.config.contacts.pop("insurer")
    c = TestClient(create_app(p, {"ops": Principal("ops", None, "s")}, realtime_clock=False))
    c.post("/tenants/testville/incidents", json={"summary": "collision", "severity": 2}, headers=OPS)
    alerts = [e for e in p.ops.exceptions.values() if e.type == "incident_notice_undelivered"]
    assert len(alerts) == 1 and "insurer" in alerts[0].message


def test_ops_queue_orders_by_severity_then_age_and_respects_seats():
    ops = OpsCenter()
    ops.add_seat("s1", "Seat 1", {"a", "b"})
    ops.add_seat("s2", "Seat 2", {"c"})
    low = ops.raise_exception(type="no_show", severity=4, tenant_id="a", at=10)
    crit_late = ops.raise_exception(type="vehicle_fault", severity=1, tenant_id="b", at=30)
    crit_early = ops.raise_exception(type="vehicle_fault", severity=1, tenant_id="a", at=20)
    other = ops.raise_exception(type="late_pickup", severity=3, tenant_id="c", at=5)
    assert [e.id for e in ops.queue("s1")] == [crit_early.id, crit_late.id, low.id]
    assert [e.id for e in ops.queue("s2")] == [other.id]
    with pytest.raises(PermissionError):
        ops.acknowledge(other.id, "s1", 40)  # seat not assigned to tenant c
    ops.resolve(low.id, 50, "rider called")
    assert low.id not in [e.id for e in ops.queue("s1")]


def test_seat_simulation_serves_critical_first():
    ops = OpsCenter()
    ops.add_seat("s", "Seat", {"a"})
    ops.raise_exception(type="incident", severity=2, tenant_id="a", at=0)  # 20 min of work
    ops.raise_exception(type="no_show", severity=4, tenant_id="a", at=1)
    ops.raise_exception(type="vehicle_fault", severity=1, tenant_id="a", at=2)
    stats = ops.simulate_seat("s", 0, 120)
    # the fault arrives while the seat is busy, but jumps the low-severity no-show
    assert stats["max_response_min_critical"] == 18 and stats["max_response_min_low"] == 31


def test_ops_keys_only_touch_exceptions_of_their_tenants(testville):
    p, rt = testville
    p.ops.add_seat("seat-tv", "TV seat", {"testville"})
    keys = {"tv": Principal("ops", {"testville"}, "seat-tv"), "other": Principal("ops", {"othertown"}, "seat-x")}
    c = TestClient(create_app(p, keys, realtime_clock=False))
    e = p.ops.raise_exception(type="no_show", severity=4, tenant_id="testville", at=600)
    assert c.get("/ops/queue", headers={"X-Api-Key": "other"}).json() == []  # unregistered seat: falls back to key's tenants
    assert c.post(f"/ops/exceptions/{e.id}/resolve", headers={"X-Api-Key": "other"}).status_code == 404
    assert c.post(f"/ops/exceptions/{e.id}/ack", headers={"X-Api-Key": "other"}).status_code == 404
    assert c.post("/ops/exceptions/nope/resolve", headers={"X-Api-Key": "tv"}).status_code == 404
    assert c.post(f"/ops/exceptions/{e.id}/ack", headers={"X-Api-Key": "tv"}).json()["status"] == "acknowledged"
    assert c.post(f"/ops/exceptions/{e.id}/resolve", headers={"X-Api-Key": "tv"}).json()["status"] == "resolved"
