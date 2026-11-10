"""Incident workflow (spec §7.4): capture -> notify (city, insurer, police/fire) -> close-out."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from ..models import Incident, Severity, new_id
from ..store import TenantScope


class Notifier(Protocol):
    def send(self, to: str, subject: str, body: str) -> dict: ...


class LogNotifier:
    """Records notifications; production swaps in email/SMS/CAD integrations."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, to: str, subject: str, body: str) -> dict:
        msg = {"to": to, "subject": subject, "body": body}
        self.sent.append(msg)
        return msg


def open_incident(
    scope: TenantScope,
    contacts: dict[str, str],
    notifier: Notifier,
    *,
    severity: Severity,
    summary: str,
    event_ids: list[str] | None = None,
    parties: list[str] | None = None,
    injuries: bool = False,
    service_date: date | None = None,
) -> Incident:
    inc = scope.add(
        Incident(
            id=new_id("inc"),
            tenant_id=scope.tenant_id,
            event_ids=event_ids or [],
            severity=severity,
            summary=summary,
            parties=parties or [],
            injuries=injuries,
        )
    )
    recipients = ["city_program_manager"]
    if severity <= Severity.high or injuries:
        recipients.append("insurer")
    if injuries:
        recipients.append("police_fire")
    for role in recipients:
        to = contacts.get(role)
        if to is None:  # record the gap instead of "sending" to nobody
            inc.notifications.append({"role": role, "to": None, "delivered": False})
            continue
        n = notifier.send(to, f"[{scope.tenant_id}] Incident {inc.id} ({severity.name})", summary)
        inc.notifications.append({"role": role, **n, "delivered": True})
    inc.status = "notified"
    return inc


def close_incident(scope: TenantScope, incident_id: str, root_cause: str, corrective_action: str) -> Incident:
    inc = scope.get(Incident, incident_id)
    inc.close_out = (
        f"Incident {inc.id} close-out\n"
        f"Severity: {inc.severity.name}\nSummary: {inc.summary}\n"
        f"Injuries: {'yes' if inc.injuries else 'no'}\nParties: {', '.join(inc.parties) or 'n/a'}\n"
        f"Notified: {', '.join(n['role'] for n in inc.notifications if n['delivered']) or 'none'}\n"
        f"Not delivered (no contact): {', '.join(n['role'] for n in inc.notifications if not n['delivered']) or 'none'}\n"
        f"Root cause: {root_cause}\nCorrective action: {corrective_action}\n"
    )
    inc.status = "closed"
    return inc
