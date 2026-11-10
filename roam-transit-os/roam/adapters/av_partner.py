"""AV partner adapter stub (spec §6, build step 10).

One subclass per AV provider fleet API. **VERIFY** which providers will expose fleet APIs
to city-owned networks and on what per-vehicle fees. Until then the
:class:`SimulatedAVProvider` client runs the vehicle inside the simulator, so the full
dispatch -> ODD enforcement -> remote-assist path can be exercised end to end.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any, Protocol

from .. import geo
from ..models import AdapterKind, Run, VehicleCapabilities
from .base import Ack, AssistContext, AssistTicket, RunPatch, VehicleAdapter, VehicleEvent

_ticket_ids = itertools.count(1)


class AVProviderClient(Protocol):
    """What we need from any AV provider's fleet API."""

    def dispatch(self, vehicle_id: str, run: Run) -> Ack: ...
    def amend(self, vehicle_id: str, run_id: str, patch: RunPatch) -> Ack: ...
    def cancel(self, vehicle_id: str, stop_id: str, reason: str) -> Ack: ...
    def subscribe(self, vehicle_id: str, on_event: Callable[[VehicleEvent], None], on_telemetry: Callable[[Any], None]) -> None: ...


class SimulatedAVProvider:
    """Provider client backed by simulator adapters (one per vehicle)."""

    def __init__(self, sims: dict[str, VehicleAdapter]):
        self.sims = sims

    def dispatch(self, vehicle_id: str, run: Run) -> Ack:
        return self.sims[vehicle_id].assign_run(run)

    def amend(self, vehicle_id: str, run_id: str, patch: RunPatch) -> Ack:
        return self.sims[vehicle_id].update_run(run_id, patch)

    def cancel(self, vehicle_id: str, stop_id: str, reason: str) -> Ack:
        return self.sims[vehicle_id].cancel_stop(stop_id, reason)

    def subscribe(self, vehicle_id, on_event, on_telemetry) -> None:
        self.sims[vehicle_id].on_event(on_event)
        self.sims[vehicle_id].on_telemetry(on_telemetry)


class AVPartnerAdapter(VehicleAdapter):
    kind = AdapterKind.av_partner

    def __init__(
        self,
        vehicle_id: str,
        capabilities: VehicleCapabilities,
        client: AVProviderClient,
        odd_geometries: dict[str, dict],
        on_assist: Callable[[AssistContext, AssistTicket], None] | None = None,
    ):
        super().__init__(vehicle_id, capabilities)
        self.client = client
        self.odd = odd_geometries
        self.on_assist = on_assist or (lambda ctx, t: None)
        self.tickets: dict[str, AssistTicket] = {}
        client.subscribe(vehicle_id, self._emit_event, self._emit_telemetry)

    def _outside_odd(self, run: Run) -> list[str]:
        bad = []
        for s in run.stops:
            if s.location is None:
                continue
            if not any(geo.point_in_geometry(s.location, g) for g in self.odd.values()):
                bad.append(s.id)
        return bad

    def assign_run(self, run: Run) -> Ack:
        bad = self._outside_odd(run)
        if bad:
            return Ack(False, f"stops outside operational design domain: {bad}")
        return self.client.dispatch(self.vehicle_id, run)

    def update_run(self, run_id: str, patch: RunPatch) -> Ack:
        bad = self._outside_odd(Run(id=run_id, tenant_id="", shift_id="", vehicle_id=self.vehicle_id, stops=patch.add_stops))
        if bad:
            return Ack(False, f"stops outside operational design domain: {bad}")
        return self.client.amend(self.vehicle_id, run_id, patch)

    def cancel_stop(self, stop_id: str, reason: str) -> Ack:
        return self.client.cancel(self.vehicle_id, stop_id, reason)

    def request_remote_assist(self, ctx: AssistContext) -> AssistTicket:
        t = AssistTicket(ticket_id=f"assist_{next(_ticket_ids):05d}", vehicle_id=self.vehicle_id)
        self.tickets[t.ticket_id] = t
        self.on_assist(ctx, t)  # lands in the ops console exceptions queue (severity high)
        self._emit_event(
            VehicleEvent(
                self.vehicle_id,
                ctx.timestamp,
                "remote_assist",
                location=ctx.location,
                payload={"ticket_id": t.ticket_id, "reason": ctx.reason},
            )
        )
        return t
