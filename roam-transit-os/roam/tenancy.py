"""Tenant runtime: everything provisioned from one tenant config (plug-and-play, spec §4.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import geo
from .config.schema import TenantConfig, hhmm_to_min
from .config.validate import ValidationReport
from .models import (
    AdapterKind,
    FundingSource,
    LonLat,
    Mode,
    ServicePolicy,
    ServiceZone,
    Shift,
    Tenant,
    Vehicle,
)


@dataclass
class TenantRuntime:
    config: TenantConfig
    tenant: Tenant
    zones: list[ServiceZone]
    policy: ServicePolicy
    vehicles: list[Vehicle]
    funding: list[FundingSource]
    travel: geo.TravelModel
    validation: ValidationReport
    gtfs_stops: list[dict[str, Any]] = field(default_factory=list)
    unstaffed_shifts: int = 0

    @property
    def id(self) -> str:
        return self.tenant.id

    def zones_for(self, mode: Mode) -> list[ServiceZone]:
        return [z for z in self.zones if z.mode == mode]

    def in_service_area(self, pt: LonLat, mode: Mode) -> ServiceZone | None:
        for z in self.zones_for(mode):
            if geo.point_in_geometry(pt, z.geometry):
                return z
        return None

    def odd_vehicle_ids(self, a: LonLat, b: LonLat) -> set[str]:
        """Vehicles allowed to serve a trip a->b: human drivers anywhere, AVs only inside their ODD."""
        zone_geo = {z.id: z.geometry for z in self.zones}
        ok: set[str] = set()
        for v in self.vehicles:
            if v.adapter_kind != AdapterKind.av_partner:
                ok.add(v.id)
            elif any(geo.point_in_geometry(a, zone_geo[z]) for z in v.odd_zone_ids) and any(
                geo.point_in_geometry(b, zone_geo[z]) for z in v.odd_zone_ids
            ):
                ok.add(v.id)
        return ok

    def shifts_for(self, service_date: date) -> list[Shift]:
        """Expand shift templates onto vehicles (round-robin) for a service date."""
        hours = self.config.hours_for(service_date.weekday())
        if hours is None:
            return []
        templates = self.config.shifts or []
        shifts: list[Shift] = []
        depot = tuple(self.config.depot)
        if not templates:  # default: every vehicle works the service span
            for v in self.vehicles:
                shifts.append(
                    Shift(
                        id=f"{self.id}:{service_date.isoformat()}:{v.id}:0",
                        tenant_id=self.id,
                        vehicle_id=v.id,
                        service_date=service_date,
                        start=hours[0] - 15,
                        end=hours[1] + 15,
                        depot=depot,  # type: ignore[arg-type]
                    )
                )
            return shifts
        targeted = {t.fleet_prefix for t in templates if t.fleet_prefix}
        last_end: dict[str, float] = {}
        per_vehicle: dict[str, int] = {}
        self.unstaffed_shifts = 0
        for tpl in sorted(templates, key=lambda s: hhmm_to_min(s.start)):
            st, en = hhmm_to_min(tpl.start), hhmm_to_min(tpl.end)
            if tpl.fleet_prefix:
                pool = [v for v in self.vehicles if v.label.rstrip("0123456789") == tpl.fleet_prefix]
            else:
                pool = [v for v in self.vehicles if v.label.rstrip("0123456789") not in targeted]
            for _ in range(tpl.count):
                free = [v for v in pool if last_end.get(v.id, -1.0) <= st]
                if not free:
                    self.unstaffed_shifts += 1  # more shifts than vehicles available at that time
                    continue
                v = min(free, key=lambda v: (per_vehicle.get(v.id, 0), v.id))
                last_end[v.id] = en
                k = per_vehicle.get(v.id, 0)
                per_vehicle[v.id] = k + 1
                shifts.append(
                    Shift(
                        id=f"{self.id}:{service_date.isoformat()}:{v.id}:{k}",
                        tenant_id=self.id,
                        vehicle_id=v.id,
                        driver_id=None if v.adapter_kind == AdapterKind.av_partner else f"drv:{v.id}:{k}",
                        service_date=service_date,
                        start=st,
                        end=en,
                        depot=depot,  # type: ignore[arg-type]
                        break_after_min=None if v.adapter_kind == AdapterKind.av_partner else tpl.break_after_min,
                        break_duration_min=tpl.break_duration_min,
                    )
                )
        return shifts


def build_runtime(
    cfg: TenantConfig,
    geoms: dict[str, dict[str, Any]],
    validation: ValidationReport,
    travel: geo.TravelModel | None = None,
    h3_res: int = 8,
) -> TenantRuntime:
    tenant = Tenant(
        id=cfg.id,
        name=cfg.name,
        type=cfg.type,
        region=cfg.region,
        timezone=cfg.timezone,
        contract_terms={"pricing": cfg.pricing.model_dump(), "phase": cfg.phase},
    )
    zones = [
        ServiceZone(
            id=z.id,
            tenant_id=cfg.id,
            name=z.name or z.id,
            geometry=geoms[z.id],
            h3_cells=geo.h3_cells_for(geoms[z.id], h3_res),
            mode=z.mode,
        )
        for z in cfg.zones
    ]
    policy = ServicePolicy(
        id=f"{cfg.id}:policy",
        tenant_id=cfg.id,
        hours={d: tuple(h) for d, h in cfg.service_hours.items() if h},  # type: ignore[misc]
        fares=cfg.fares,
        eligibility_rules=cfg.eligibility,
        booking_rules=cfg.booking_rules.model_dump(exclude_none=True),
        ada_rules=cfg.ada_rules.model_dump() if cfg.ada_rules else None,
    )
    vehicles: list[Vehicle] = []
    for fe in cfg.fleet:
        for i in range(fe.count):
            vehicles.append(
                Vehicle(
                    id=f"{cfg.id}:{fe.prefix}{i + 1:02d}",
                    tenant_id=cfg.id,
                    adapter_kind=fe.adapter,
                    seats=fe.seats,
                    wheelchair_positions=fe.wheelchair_positions,
                    max_range_km=fe.max_range_km,
                    lease_ref=fe.lease_ref,
                    odd_zone_ids=fe.odd_zone_ids,
                    label=f"{fe.prefix}{i + 1:02d}",
                )
            )
    funding = [
        FundingSource(id=f.id, tenant_id=cfg.id, type=f.type, name=f.name, account_ref=f.account_ref, rules=f.rules)
        for f in cfg.funding_sources
    ]
    return TenantRuntime(
        config=cfg,
        tenant=tenant,
        zones=zones,
        policy=policy,
        vehicles=vehicles,
        funding=funding,
        travel=travel or geo.HaversineTravelModel(),
        validation=validation,
    )
