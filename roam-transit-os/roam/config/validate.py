"""Tenant config validation (spec §7.1).

Three severities:
* ``errors``: config cannot be provisioned.
* ``golive_blockers``: may be provisioned for simulation / proposals, but not for live service.
* ``warnings``: worth a human look.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .. import geo
from ..models import AdapterKind, Mode
from .schema import DAYS, TenantConfig, hhmm_to_min

POLICY_PATH = Path(__file__).with_name("policy.yaml")


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    golive_blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def can_go_live(self) -> bool:
        return not self.errors and not self.golive_blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "can_go_live": self.can_go_live,
            "errors": self.errors,
            "golive_blockers": self.golive_blockers,
            "warnings": self.warnings,
        }


def load_policy() -> dict[str, Any]:
    return yaml.safe_load(POLICY_PATH.read_text())


def validate(cfg: TenantConfig, geoms: dict[str, dict[str, Any]], policy: dict[str, Any] | None = None) -> ValidationReport:
    rep = ValidationReport()
    policy = policy or load_policy()
    E, B, W = rep.errors.append, rep.golive_blockers.append, rep.warnings.append

    # ---- corporate guardrails (spec §3)
    for ex in policy.get("excluded_jurisdictions", []):
        if (
            cfg.region.get("state", "").upper() == ex["state"].upper()
            and cfg.region.get("jurisdiction", "").strip().lower() == ex["jurisdiction"].lower()
        ):
            E(f"jurisdiction excluded: {ex['jurisdiction']}, {ex['state']}: {ex['reason']}")
    for blk in policy.get("blocked_pending_decision", []):
        if blk["tenant_id"] == cfg.id:
            B(f"pending governance decision: {blk['question']}")

    # ---- zones
    zone_ids = [z.id for z in cfg.zones]
    if len(set(zone_ids)) != len(zone_ids):
        E("duplicate zone ids")
    for z in cfg.zones:
        g = geoms.get(z.id)
        if g is None:
            E(f"zone {z.id}: geometry not loaded")
            continue
        for msg in geo.validate_polygon(g):
            E(f"zone {z.id}: {msg}")
        if not rep.errors:
            a = geo.area_km2(g)
            if a < 0.5:
                W(f"zone {z.id}: very small ({a:.2f} km2)")
            if a > 5000:
                W(f"zone {z.id}: very large ({a:.0f} km2) - check units/projection")
            if cfg.road_network_bbox:
                x0, y0, x1, y1 = geo.bbox(g)
                rx0, ry0, rx1, ry1 = cfg.road_network_bbox
                if x0 < rx0 or y0 < ry0 or x1 > rx1 or y1 > ry1:
                    E(f"zone {z.id}: extends outside the loaded road network extent")
    if not cfg.road_network_bbox:
        W("no road network loaded: travel times use the haversine model (load OSRM/Valhalla before go-live)")
        B("road network (OSRM/Valhalla extract) not loaded")

    zone_modes = {z.mode for z in cfg.zones}
    for m in cfg.modes:
        if m not in zone_modes:
            E(f"mode {m.value} has no service zone")
    if not any(geo.point_in_geometry(tuple(cfg.depot), geoms[z.id]) for z in cfg.zones if z.id in geoms):
        W("depot is outside every service zone (deadhead will be counted)")

    # ---- hours
    any_hours = False
    for d in DAYS:
        h = cfg.service_hours.get(d)
        if h:
            any_hours = True
            try:
                if hhmm_to_min(h[1]) <= hhmm_to_min(h[0]):
                    E(f"service_hours.{d}: end must be after start")
            except ValueError:
                E(f"service_hours.{d}: use HH:MM")
    if not any_hours:
        E("service_hours: no service day configured")

    # ---- fares: complete for every mode
    for m in cfg.modes:
        f = cfg.fares.get(m.value)
        if not f or "base" not in f:
            E(f"fares.{m.value}: missing (need at least 'base')")

    # ---- ADA (only if paratransit)
    if Mode.paratransit in cfg.modes:
        if cfg.ada_rules is None:
            E("paratransit mode requires ada_rules")
        else:
            if cfg.ada_rules.denials_allowed != 0:
                E("ada_rules.denials_allowed must be 0 (no capacity-constrained denials)")
            fare = cfg.fares.get("paratransit", {}).get("base")
            if fare is not None and fare > cfg.ada_rules.fixed_route_fare * cfg.ada_rules.max_fare_multiple + 1e-9:
                E(
                    f"paratransit fare ${fare:.2f} exceeds {cfg.ada_rules.max_fare_multiple:g}x fixed-route fare "
                    f"(${cfg.ada_rules.fixed_route_fare:.2f})"
                )
        if cfg.booking_rules.paratransit is None:
            E("paratransit mode requires booking_rules.paratransit")
        else:
            pr = cfg.booking_rules.paratransit
            if pr.min_advance_days > 1:
                E("paratransit must accept next-day trips (min_advance_days <= 1)")
            if pr.max_advance_days > 14:
                E("paratransit max_advance_days may not exceed 14")
            if pr.negotiation_window_min > 60:
                E("ADA: pickup negotiation may not exceed +/-60 minutes")
        if not any(fe.wheelchair_positions > 0 for fe in cfg.fleet):
            E("paratransit fleet has no wheelchair positions")
    for m in (Mode.microtransit, Mode.av_network):
        if m in cfg.modes and getattr(cfg.booking_rules, m.value) is None:
            E(f"{m.value} mode requires booking_rules.{m.value}")

    # ---- fleet / phase / AV
    if not cfg.fleet:
        E("fleet is empty")
    for fe in cfg.fleet:
        for zid in fe.odd_zone_ids:
            if zid not in zone_ids:
                E(f"fleet {fe.prefix}: odd_zone_id {zid} is not a configured zone")
        if fe.adapter == AdapterKind.av_partner:
            if not fe.odd_zone_ids:
                E(f"fleet {fe.prefix}: av_partner vehicles need odd_zone_ids (operational design domain)")
            if not cfg.compliance.state_av_profile:
                B(f"fleet {fe.prefix}: no state AV authorization profile (Autonomy OS) on file")
            if fe.provider is None:
                W(f"fleet {fe.prefix}: av_partner provider not named (VERIFY provider fleet API access)")
            if cfg.phase == 1:
                W(f"fleet {fe.prefix}: av_partner vehicles configured in a phase-1 tenant")
    if cfg.phase == 3 and any(fe.adapter == AdapterKind.human_driver for fe in cfg.fleet):
        W("phase 3 tenant still has human_driver vehicles")
    shift_total = sum(s.count for s in cfg.shifts)
    if shift_total > cfg.vehicle_count * 3:
        W("more than 3 shifts per vehicle per day configured")
    for s in cfg.shifts:
        if hhmm_to_min(s.end) <= hhmm_to_min(s.start):
            E(f"shift {s.start}-{s.end}: end must be after start")

    # ---- funding
    if not cfg.funding_sources:
        E("at least one funding source is required")

    # ---- compliance reminders (spec §10)
    if cfg.compliance.federal_funds:
        W("federal funds: FTA drug & alcohol testing, Section 13(c) labor protections and NTD reporting apply")
        if any(fe.adapter == AdapterKind.av_partner for fe in cfg.fleet):
            B("federal funds + AV: a Section 13(c) labor-protection plan is required for the driverless transition")
    if cfg.compliance.hipaa is False and any(f.type.value == "medicaid_nemt" for f in cfg.funding_sources):
        E("medicaid_nemt funding requires compliance.hipaa = true")
    for key in ("city_program_manager", "insurer"):
        if key not in cfg.contacts:
            B(f"contacts.{key} missing (incident notifications)")
    return rep
