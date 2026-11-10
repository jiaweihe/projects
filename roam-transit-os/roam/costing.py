"""Program cost model: phase 1 (human-driven), 2 (hybrid), 3 (driverless).

Removing the driver does not remove all labor (spec §2.4): phase 3 budgets remote
supervisors, field technicians, cleaning, charging, AV software licences and attendants.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

COST_MODEL_PATH = Path(__file__).parent / "config" / "cost_model.yaml"


def load_cost_model(path: str | Path | None = None) -> dict[str, Any]:
    return yaml.safe_load(Path(path or COST_MODEL_PATH).read_text())


@dataclass
class Operations:
    """Service volume for a period (from simulation or actuals)."""

    vehicles: int
    revenue_hours: float
    revenue_km: float
    total_km: float
    trips: int
    service_days: float
    months: float
    wheelchair_trips: int = 0


def _roam_fees(ops: Operations, cm: dict, pricing: dict | None, driverless_share: float) -> dict[str, float]:
    p = {**cm["roam_fees"], **(pricing or {})}
    platform = ops.vehicles * p["platform_fee_per_vehicle_month"] * ops.months
    rate = p["ops_fee_per_vrh"] * (1 - driverless_share) + p.get("ops_fee_per_vrh_driverless", p["ops_fee_per_vrh"]) * driverless_share
    return {"roam_platform_fee": platform, "roam_ops_fee": ops.revenue_hours * rate}


def phase_cost(phase: int, ops: Operations, cm: dict | None = None, pricing: dict | None = None) -> dict[str, float]:
    cm = cm or load_cost_model()
    p1, p2, p3 = cm["phase1"], cm["phase2"], cm["phase3"]
    av_share = {1: 0.0, 2: p2["av_share_of_fleet"], 3: 1.0}[phase]
    hv = ops.vehicles * (1 - av_share)
    av = ops.vehicles * av_share
    vrh_h, vrh_a = ops.revenue_hours * (1 - av_share), ops.revenue_hours * av_share
    km_h, km_a = ops.total_km * (1 - av_share), ops.total_km * av_share
    lines: dict[str, float] = {}
    # human-driven share
    lines["drivers"] = vrh_h * p1["paid_hours_per_revenue_hour"] * p1["driver_cost_per_hour"]
    lines["vehicle_leases"] = hv * p1["vehicle_lease_per_month"] * ops.months + av * p3["av_vehicle_lease_per_month"] * ops.months
    lines["insurance"] = hv * p1["insurance_per_vehicle_month"] * ops.months + av * p3["insurance_per_vehicle_month"] * ops.months
    lines["energy_maintenance"] = km_h * p1["energy_maintenance_per_km"] + km_a * (p3["charging_per_km"] + p3["maintenance_per_km"])
    if av:
        av_hours = vrh_a * p1["paid_hours_per_revenue_hour"]
        lines["av_software_licenses"] = av * p3["av_software_license_per_vehicle_month"] * ops.months
        lines["remote_supervision"] = av_hours / p3["vehicles_per_remote_supervisor"] * p3["remote_supervisor_cost_per_hour"]
        lines["field_technicians"] = av_hours * p3["field_tech_cost_per_vehicle_hour"]
        lines["cleaning"] = av * p3["cleaning_per_vehicle_day"] * ops.service_days
        lines["safety_attendants"] = av_hours * p2.get("safety_attendant_share", 0.0) * p1["driver_cost_per_hour"]
        lines["accessibility_attendants"] = (
            ops.wheelchair_trips * av_share * p3["wheelchair_attendant_share"] * p3["attendant_cost_per_trip"]
        )
    lines.update(_roam_fees(ops, cm, pricing, av_share))
    total = sum(lines.values())
    roam = lines["roam_platform_fee"] + lines["roam_ops_fee"]
    lines["total"] = total
    lines["roam_take_share"] = roam / total if total else 0.0
    lines["cost_per_trip"] = total / ops.trips if ops.trips else 0.0
    lines["cost_per_vrh"] = total / ops.revenue_hours if ops.revenue_hours else 0.0
    return lines


def turnkey_benchmark(ops: Operations, cm: dict | None = None) -> dict[str, float]:
    b = (cm or load_cost_model())["benchmarks"]
    lo, hi = ops.revenue_hours * b["turnkey_vrh_low"], ops.revenue_hours * b["turnkey_vrh_high"]
    return {
        "turnkey_low": lo,
        "turnkey_high": hi,
        "turnkey_cost_per_trip_low": lo / ops.trips if ops.trips else 0.0,
        "turnkey_cost_per_trip_high": hi / ops.trips if ops.trips else 0.0,
    }
