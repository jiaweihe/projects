"""Core data model (spec §8).

Every tenant-owned record carries ``tenant_id`` (design principle 2). Times inside a
service day are expressed as *minutes after local midnight* of ``service_date`` so the
scheduler and simulator can do plain arithmetic; the API layer converts to and from
wall-clock datetimes using the tenant's timezone.
"""

from __future__ import annotations

import itertools
from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

LonLat = tuple[float, float]  # (lon, lat), GeoJSON order

_counters: dict[str, itertools.count] = {}


def new_id(prefix: str) -> str:
    """Readable, process-unique ids (``trip_000042``). Swap for UUIDs in Postgres."""
    c = _counters.setdefault(prefix, itertools.count(1))
    return f"{prefix}_{next(c):06d}"


# --------------------------------------------------------------------------- enums
class TenantType(str, Enum):
    city = "city"
    county = "county"
    transit_agency = "transit_agency"
    community_org = "community_org"


class Mode(str, Enum):
    paratransit = "paratransit"
    microtransit = "microtransit"
    av_network = "av_network"


class Channel(str, Enum):
    app = "app"
    web = "web"
    ivr = "ivr"
    agent = "agent"


class AdapterKind(str, Enum):
    human_driver = "human_driver"
    av_partner = "av_partner"
    simulator = "simulator"


class AccessibilityNeed(str, Enum):
    wheelchair = "wheelchair"
    ambulatory_assist = "ambulatory_assist"
    service_animal = "service_animal"
    visual_impairment = "visual_impairment"
    hearing_impairment = "hearing_impairment"
    personal_care_attendant = "personal_care_attendant"


class EligibilityStatus(str, Enum):
    none = "none"  # general public only
    certified = "certified"  # ADA paratransit eligible
    conditional = "conditional"
    temporary = "temporary"
    pending = "pending"
    expired = "expired"


class FundingType(str, Enum):
    city = "city"
    county = "county"
    institution = "institution"
    grant = "grant"
    medicaid_nemt = "medicaid_nemt"  # v0.2


class TripStatus(str, Enum):
    requested = "requested"
    booked = "booked"  # accepted with a negotiated pickup time
    scheduled = "scheduled"  # placed on a run
    en_route = "en_route"
    onboard = "onboard"
    completed = "completed"
    no_show = "no_show"
    cancelled = "cancelled"
    denied = "denied"  # MUST be zero for ADA paratransit; always logged + alerted
    rejected = "rejected"  # failed a business rule (outside zone, ineligible...), not a capacity denial


class StopType(str, Enum):
    pickup = "pickup"
    dropoff = "dropoff"
    break_ = "break"


class StopStatus(str, Enum):
    planned = "planned"
    arrived = "arrived"
    done = "done"
    no_show = "no_show"
    cancelled = "cancelled"


class Severity(int, Enum):
    critical = 1  # injury / safety
    high = 2  # AV remote assist, vehicle fault with riders
    medium = 3  # late pickups, ADA denial
    low = 4  # no-shows, informational


# ------------------------------------------------------------------------- records
class Tenant(BaseModel):
    id: str
    name: str
    type: TenantType
    region: dict[str, str]  # {"state": "NJ", "jurisdiction": "Mercer County"}
    timezone: str = "America/New_York"
    contract_terms: dict[str, Any] = Field(default_factory=dict)
    data_export_policy: str = "full_export_any_time_no_exit_fee"

    @property
    def tenant_id(self) -> str:  # a tenant row belongs to itself (row-level security)
        return self.id


class ServiceZone(BaseModel):
    id: str
    tenant_id: str
    name: str = ""
    geometry: dict[str, Any]  # GeoJSON Polygon / MultiPolygon
    h3_cells: list[str] = Field(default_factory=list)
    mode: Mode


class ServicePolicy(BaseModel):
    id: str
    tenant_id: str
    hours: dict[str, tuple[str, str]]
    fares: dict[str, dict[str, float]]
    eligibility_rules: dict[str, Any]
    booking_rules: dict[str, Any]
    ada_rules: dict[str, Any] | None = None
    version: int = 1


class Rider(BaseModel):
    """Minimal personal data by design: no DOB, no diagnosis, no address book beyond saved places."""

    id: str
    tenant_id: str
    contact: dict[str, str] = Field(default_factory=dict)  # {"phone": ..., "sms_opt_in": "yes"}
    accessibility_needs: list[AccessibilityNeed] = Field(default_factory=list)
    eligibility_status: EligibilityStatus = EligibilityStatus.none
    eligibility_expires: date | None = None
    saved_places: dict[str, LonLat] = Field(default_factory=dict)

    @property
    def uses_wheelchair(self) -> bool:
        return AccessibilityNeed.wheelchair in self.accessibility_needs


class FundingSource(BaseModel):
    id: str
    tenant_id: str
    type: FundingType
    name: str = ""
    account_ref: str = ""
    rules: dict[str, Any] = Field(default_factory=dict)


class TripRequest(BaseModel):
    id: str
    tenant_id: str
    rider_id: str
    mode: Mode
    channel: Channel
    origin: LonLat
    destination: LonLat
    service_date: date
    requested_time: float  # minutes after midnight
    time_type: Literal["pickup", "appointment"] = "pickup"
    window: tuple[float, float] | None = None  # negotiated pickup window [start, end]
    negotiated_pickup: float | None = None
    wheelchair: bool = False
    companions: int = 0
    funding_source_id: str | None = None
    standing_order_id: str | None = None
    status: TripStatus = TripStatus.requested
    status_reason: str = ""
    vehicle_id: str | None = None
    pickup_arrival: float | None = None  # vehicle arrival at pickup (on-time basis)
    actual_pickup: float | None = None
    actual_dropoff: float | None = None
    request_made_at: float | None = None  # minute the request was made (real-time wait basis)
    direct_km: float | None = None
    fare: float = 0.0

    @property
    def seats(self) -> int:
        return (0 if self.wheelchair else 1) + self.companions


class StandingOrder(BaseModel):
    """Subscription trip (e.g., dialysis Mon/Wed/Fri)."""

    id: str
    tenant_id: str
    rider_id: str
    weekdays: list[int]  # 0 = Monday
    origin: LonLat
    destination: LonLat
    requested_time: float
    time_type: Literal["pickup", "appointment"] = "pickup"
    start: date
    end: date | None = None
    funding_source_id: str | None = None


class VehicleCapabilities(BaseModel):
    seats: int
    wheelchair_positions: int
    max_range_km: float = 400.0
    remote_assist: bool = False
    odd_zone_ids: list[str] | None = None


class Vehicle(BaseModel):
    id: str
    tenant_id: str
    adapter_kind: AdapterKind
    seats: int
    wheelchair_positions: int
    max_range_km: float = 400.0
    lease_ref: str = ""
    odd_zone_ids: list[str] = Field(default_factory=list)
    label: str = ""

    def capabilities(self) -> VehicleCapabilities:
        return VehicleCapabilities(
            seats=self.seats,
            wheelchair_positions=self.wheelchair_positions,
            max_range_km=self.max_range_km,
            remote_assist=self.adapter_kind == AdapterKind.av_partner,
            odd_zone_ids=self.odd_zone_ids or None,
        )


class Driver(BaseModel):
    id: str
    tenant_id: str
    operator_partner: str = ""
    certifications: list[str] = Field(default_factory=list)


class Shift(BaseModel):
    id: str
    tenant_id: str
    vehicle_id: str
    driver_id: str | None = None
    service_date: date
    start: float
    end: float
    depot: LonLat
    break_after_min: float | None = 240.0
    break_duration_min: float = 30.0


class Stop(BaseModel):
    id: str
    run_id: str
    trip_request_id: str | None
    type: StopType
    location: LonLat | None
    earliest: float
    latest: float
    service_min: float = 2.0
    eta: float | None = None
    actual: float | None = None
    status: StopStatus = StopStatus.planned


class Run(BaseModel):
    id: str
    tenant_id: str
    shift_id: str
    vehicle_id: str
    stops: list[Stop] = Field(default_factory=list)
    status: Literal["planned", "assigned", "active", "completed"] = "planned"
    shift_start: float | None = None
    shift_end: float | None = None


class Event(BaseModel):
    id: str
    tenant_id: str
    vehicle_id: str | None
    type: str  # arrival, boarding, dropoff, no_show, fault, telemetry, remote_assist, denial ...
    timestamp: float
    service_date: date
    location: LonLat | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class Incident(BaseModel):
    id: str
    tenant_id: str
    event_ids: list[str] = Field(default_factory=list)
    severity: Severity
    summary: str
    parties: list[str] = Field(default_factory=list)
    injuries: bool = False
    notifications: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["open", "notified", "closed"] = "open"
    close_out: str = ""


class Complaint(BaseModel):
    id: str
    tenant_id: str
    service_date: date
    trip_request_id: str | None = None
    category: str = "service"
    text: str = ""


class Invoice(BaseModel):
    id: str
    tenant_id: str
    period: str  # "2026-11"
    vehicles: int
    platform_fee: float
    revenue_hours: float
    ops_fee: float
    performance_adj: float
    performance_detail: dict[str, float] = Field(default_factory=dict)
    total: float


class KPISnapshot(BaseModel):
    tenant_id: str
    period: str
    metrics: dict[str, float]
