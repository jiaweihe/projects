"""Tenant configuration (spec §7.1): one YAML/JSON file + a zone upload = a live city."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from ..models import AdapterKind, FundingType, Mode, TenantType

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def hhmm_to_min(s: str) -> float:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


class ZoneConfig(BaseModel):
    id: str
    name: str = ""
    mode: Mode
    geometry: dict[str, Any] | None = None
    geometry_file: str | None = None

    @model_validator(mode="after")
    def _one_geometry(self) -> ZoneConfig:
        if (self.geometry is None) == (self.geometry_file is None):
            raise ValueError(f"zone {self.id}: give exactly one of geometry / geometry_file")
        return self


class ParatransitBookingRules(BaseModel):
    min_advance_days: int = 1  # ADA: next-day service
    max_advance_days: int = 7  # ADA allows up to 14
    booking_cutoff: str = "17:00"  # day-before reservation cutoff (local)
    negotiation_window_min: float = 60  # ADA: may negotiate pickup +/- 1 hour
    pickup_window_min: float = 30  # on-time window after negotiated pickup
    early_window_min: float = 0  # driver may arrive this early (rider not obliged to board)
    max_ride_factor: float = 2.0
    max_ride_extra_min: float = 20
    max_ride_cap_min: float = 90
    service_min: float = 3.0  # dwell, wheelchair securement adds more
    wheelchair_service_min: float = 6.0
    no_show_wait_min: float = 5.0


class MicrotransitBookingRules(BaseModel):
    realtime: bool = True
    max_advance_days: int = 7
    max_wait_min: float = 30
    pickup_window_min: float = 15
    walk_to_stop_m: float = 400
    virtual_stops: list[tuple[float, float]] = Field(default_factory=list)
    max_ride_factor: float = 2.2
    max_ride_extra_min: float = 15
    max_ride_cap_min: float = 75
    service_min: float = 1.5
    wheelchair_service_min: float = 5.0


class BookingRules(BaseModel):
    paratransit: ParatransitBookingRules | None = None
    microtransit: MicrotransitBookingRules | None = None
    av_network: MicrotransitBookingRules | None = None


class ADARules(BaseModel):
    """ADA complementary paratransit parameters (49 CFR Part 37 Subpart F)."""

    denials_allowed: int = 0
    fixed_route_fare: float  # paratransit fare may not exceed 2x the fixed-route fare
    max_fare_multiple: float = 2.0
    service_area_buffer_miles: float = 0.75
    eligibility_certification_required: bool = True


class FleetEntry(BaseModel):
    adapter: AdapterKind
    count: int = Field(ge=1)
    seats: int = Field(ge=0)
    wheelchair_positions: int = Field(ge=0)
    max_range_km: float = 400
    prefix: str = "VEH"
    odd_zone_ids: list[str] = Field(default_factory=list)
    lease_ref: str = ""
    provider: str | None = None  # av_partner provider key


class ShiftTemplate(BaseModel):
    start: str
    end: str
    count: int = Field(ge=1)
    fleet_prefix: str | None = None  # restrict to one fleet entry; untargeted fleets share the rest
    break_after_min: float | None = 240
    break_duration_min: float = 30


class FundingSourceConfig(BaseModel):
    id: str
    type: FundingType
    name: str = ""
    account_ref: str = ""
    rules: dict[str, Any] = Field(default_factory=dict)


class PerformanceTerms(BaseModel):
    """Bonus/penalty as % of the operations fee, per KPI (spec §2.2)."""

    otp_target: float = 0.90
    otp_pct_per_point: float = 0.5  # +/-0.5% of ops fee per OTP point vs target
    wait_p95_target_min: float = 30
    wait_pct_per_min: float = 0.25
    complaints_per_1k_target: float = 2.0
    complaints_pct_per_unit: float = 1.0
    cost_per_trip_target: float | None = None
    cost_pct_per_dollar: float = 0.5
    cap_pct: float = 10.0  # adjustment capped at +/-10% of ops fee


class PricingTerms(BaseModel):
    # PLACEHOLDER rates, chosen so Roam's take is ~15-20% of phase-1 program cost (spec §2.2).
    platform_fee_per_vehicle_month: float = 1000.0
    ops_fee_per_vrh: float = 8.0
    ops_fee_per_vrh_driverless: float = 12.0
    performance: PerformanceTerms = Field(default_factory=PerformanceTerms)


class Compliance(BaseModel):
    federal_funds: bool = False  # triggers FTA drug & alcohol, Section 13(c), NTD
    hipaa: bool = False
    title_vi: bool = True
    state_av_profile: str | None = None  # Autonomy OS jurisdiction profile id


class Branding(BaseModel):
    display_name: str
    primary_color: str = "#1f6feb"
    phone_number: str = ""
    info_url: str = ""


class TenantConfig(BaseModel):
    id: str
    name: str
    type: TenantType
    region: dict[str, str]
    timezone: str = "America/New_York"
    phase: Literal[1, 2, 3] = 1
    modes: list[Mode]
    zones: list[ZoneConfig]
    service_hours: dict[str, tuple[str, str] | None]
    fares: dict[str, dict[str, float]]
    eligibility: dict[str, Any] = Field(default_factory=dict)
    booking_rules: BookingRules
    ada_rules: ADARules | None = None
    fleet: list[FleetEntry]
    shifts: list[ShiftTemplate] = Field(default_factory=list)
    depot: tuple[float, float]
    funding_sources: list[FundingSourceConfig]
    branding: Branding
    pricing: PricingTerms = Field(default_factory=PricingTerms)
    compliance: Compliance = Field(default_factory=Compliance)
    contacts: dict[str, str] = Field(default_factory=dict)
    gtfs_feed: str | None = None  # path to a fixed-route GTFS feed for transfers
    road_network_bbox: tuple[float, float, float, float] | None = None
    notes: list[str] = Field(default_factory=list)

    # ---------------------------------------------------------------- helpers
    def hours_for(self, weekday: int) -> tuple[float, float] | None:
        h = self.service_hours.get(DAYS[weekday])
        return None if not h else (hhmm_to_min(h[0]), hhmm_to_min(h[1]))

    @property
    def vehicle_count(self) -> int:
        return sum(f.count for f in self.fleet)


def load_config(path: str | Path) -> tuple[TenantConfig, dict[str, dict[str, Any]]]:
    """Load a tenant config and resolve zone geometry files relative to the config."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) if path.suffix in (".yaml", ".yml") else json.loads(path.read_text())
    cfg = TenantConfig.model_validate(raw)
    geoms: dict[str, dict[str, Any]] = {}
    for z in cfg.zones:
        if z.geometry is not None:
            geoms[z.id] = z.geometry
        else:
            g = json.loads((path.parent / z.geometry_file).read_text())  # type: ignore[arg-type]
            if g.get("type") == "FeatureCollection":
                g = g["features"][0]["geometry"] if len(g["features"]) == 1 else g
            elif g.get("type") == "Feature":
                g = g["geometry"]
            geoms[z.id] = g
    return cfg, geoms


def config_from_dict(raw: dict[str, Any]) -> tuple[TenantConfig, dict[str, dict[str, Any]]]:
    cfg = TenantConfig.model_validate(raw)
    geoms = {z.id: z.geometry for z in cfg.zones if z.geometry is not None}
    return cfg, geoms  # type: ignore[return-value]
