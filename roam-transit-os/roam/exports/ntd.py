"""National Transit Database monthly ridership template (demand response), spec §7.7.

Produces the service and ridership totals agencies enter on the NTD monthly ridership
form for mode DR (and DT for taxi-like service). **VERIFY** the current NTD reporting
manual (forms, mode codes, type-of-service PT vs DO, and any microtransit guidance)
before submitting anything for an FTA-funded service.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from typing import TYPE_CHECKING

from ..kpi import KM_PER_MILE, compute_kpis
from ..models import Mode, TripRequest, TripStatus

if TYPE_CHECKING:
    from ..platform import Platform


def ntd_monthly(platform: "Platform", tenant_id: str, start: date, end: date) -> dict[str, float | str]:
    rt = platform.tenant(tenant_id)
    k = compute_kpis(platform, tenant_id, start, end)
    trips = [t for t in platform.store.scope(tenant_id).list(TripRequest, status=TripStatus.completed) if start <= t.service_date <= end]
    pmt = sum((t.direct_km or 0) / KM_PER_MILE * (1 + t.companions) for t in trips)
    # VOMS: max vehicles operated simultaneously in the period
    voms = 0
    d = start
    while d <= end:
        disp = platform.dispatchers.get((tenant_id, d))
        if disp:
            voms = max(voms, len({u.vehicle_id for u in disp.units if disp.rt[u.unit_id].trips_served}))
        d += timedelta(days=1)
    return {
        "agency": rt.config.name,
        "period": f"{start.isoformat()}..{end.isoformat()}",
        "mode": "DR",
        "type_of_service": "PT",  # purchased transportation (contract operator) - VERIFY per contract structure
        "upt": sum(1 + t.companions for t in trips),
        "upt_paratransit": sum(1 + t.companions for t in trips if t.mode == Mode.paratransit),
        "vrm": round(k["vehicle_revenue_km"] / KM_PER_MILE, 1),
        "vrh": k["vehicle_revenue_hours"],
        "vom_total_miles": round(k["vehicle_total_km"] / KM_PER_MILE, 1),
        "voms": voms,
        "pmt": round(pmt, 1),
        "ada_trips_denied": k["ada_denials"],
    }


def ntd_csv(row: dict) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(row.keys()), lineterminator="\n")
    w.writeheader()
    w.writerow(row)
    return buf.getvalue()
