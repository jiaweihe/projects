"""Invoices (spec §2.2, §7.5): platform fee + operations fee + performance adjustment.

Not a percentage of budget: the platform fee is per vehicle per month and the ops fee is
per vehicle revenue hour, so Roam's dollars hold steady as drivers come out of the cost base.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date
from typing import TYPE_CHECKING

from .kpi import compute_kpis
from .models import Invoice

if TYPE_CHECKING:
    from .platform import Platform


def performance_adjustment(kpis: dict, terms, ops_fee: float) -> tuple[float, dict[str, float]]:
    """Signed adjustment in dollars, capped at +/-cap_pct of the ops fee."""
    pct: dict[str, float] = {}
    pct["on_time"] = (kpis["on_time_performance"] - terms.otp_target) * 100 * terms.otp_pct_per_point
    pct["wait_p95"] = (terms.wait_p95_target_min - kpis["wait_p95_min"]) * terms.wait_pct_per_min
    pct["complaints"] = (terms.complaints_per_1k_target - kpis["complaints_per_1k_trips"]) * terms.complaints_pct_per_unit
    if terms.cost_per_trip_target and kpis["cost_per_trip"]:
        pct["cost_per_trip"] = (terms.cost_per_trip_target - kpis["cost_per_trip"]) * terms.cost_pct_per_dollar
    if kpis.get("ada_denials", 0) > 0:
        pct["ada_denials"] = -terms.cap_pct  # any ADA denial forfeits the bonus and takes the max penalty
    total_pct = max(-terms.cap_pct, min(terms.cap_pct, sum(pct.values())))
    detail = {k: round(v, 3) for k, v in pct.items()}
    detail["total_pct"] = round(total_pct, 3)
    return round(ops_fee * total_pct / 100, 2), detail


def build_invoice(platform: Platform, tenant_id: str, period: str, start: date | None = None, end: date | None = None) -> Invoice:
    """Invoice for a calendar month ``YYYY-MM`` (or an explicit date range within it)."""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise ValueError(f"period must be YYYY-MM, got {period!r}")
    y, m = int(period[:4]), int(period[5:])
    days_in_month = monthrange(y, m)[1]
    first, last = date(y, m, 1), date(y, m, days_in_month)
    start, end = start or first, end or last
    if not (first <= start <= end <= last):
        raise ValueError(f"billing range {start}..{end} is not within {period}")
    rt = platform.tenant(tenant_id)
    pricing = rt.config.pricing
    k = compute_kpis(platform, tenant_id, start, end)
    vehicles = len(rt.vehicles)
    proration = ((end - start).days + 1) / days_in_month
    platform_fee = round(vehicles * pricing.platform_fee_per_vehicle_month * proration, 2)
    ops_fee = round(k["vehicle_revenue_hours"] * pricing.ops_fee_per_vrh, 2)
    adj, detail = performance_adjustment(k, pricing.performance, ops_fee)
    inv = Invoice(
        id=f"inv:{tenant_id}:{period}",
        tenant_id=tenant_id,
        period=period,
        vehicles=vehicles,
        platform_fee=platform_fee,
        revenue_hours=k["vehicle_revenue_hours"],
        ops_fee=ops_fee,
        performance_adj=adj,
        performance_detail=detail,
        total=round(platform_fee + ops_fee + adj, 2),
    )
    platform.store.scope(tenant_id).add(inv)
    return inv
