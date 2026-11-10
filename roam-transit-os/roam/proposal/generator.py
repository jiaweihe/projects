"""Proposal generator (Roam service layer, spec §7.8): the go-to-market engine.

Input: a city boundary (+ optional population and current transit cost).
Method: H3 hexagons over the boundary -> demand estimate -> simulate a representative
sample day with the simulator adapter -> size the fleet until ADA denials are zero and
on-time performance is >= 90% -> scale to full demand -> three-phase cost model vs the
turnkey benchmark ($65-90 per vehicle revenue hour).
Output: a dict (service design + costs) and a one-page PDF.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .. import geo
from ..adapters.simulator import SimParams
from ..config.schema import config_from_dict
from ..config.validate import load_policy
from ..costing import Operations, load_cost_model, phase_cost, turnkey_benchmark
from ..sim.demand import DemandSpec

WEEKDAYS_PER_YEAR = 255
SATURDAY_EQUIV = 52 * 0.5  # Saturday service ~ half a weekday


@dataclass
class ProposalInput:
    name: str
    state: str
    boundary: dict[str, Any]  # GeoJSON Polygon/MultiPolygon
    jurisdiction: str | None = None
    population: int | None = None
    density_per_km2: float = 1000.0  # ASSUMPTION when population is unknown (VERIFY with Census/ACS)
    modes: tuple[str, ...] = ("paratransit", "microtransit")
    paratransit_trips_per_capita_day: float = 0.0013  # ASSUMPTION (~0.35 trips/capita/yr)
    microtransit_trips_per_capita_day: float = 0.0015  # ASSUMPTION
    microtransit_boundary: dict[str, Any] | None = None  # smaller zone; defaults to boundary
    current_annual_cost: float | None = None
    current_annual_trips: float | None = None
    depot: tuple[float, float] | None = None
    timezone: str = "America/New_York"
    sample_cap: int = 70  # trips per mode in the representative simulated day
    seed: int = 5
    notes: list[str] = field(default_factory=list)


def slug(name: str) -> str:
    """Filesystem-safe file stem for a proposal (no path separators, no dots)."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:80] or "proposal"


def _synthetic_config(inp: ProposalInput, vehicles: int) -> dict[str, Any]:
    zones = []
    modes = list(inp.modes)
    if "paratransit" in modes:
        zones.append({"id": "pz", "mode": "paratransit", "geometry": inp.boundary})
    if "microtransit" in modes:
        zones.append({"id": "mz", "mode": "microtransit", "geometry": inp.microtransit_boundary or inp.boundary})
    depot = inp.depot
    if depot is None:
        x0, y0, x1, y1 = geo.bbox(inp.boundary)
        depot = ((x0 + x1) / 2, (y0 + y1) / 2)
        if not geo.point_in_geometry(depot, inp.boundary):
            import random

            depot = geo.random_point_in(inp.boundary, random.Random(1))
    a = max(1, math.ceil(vehicles * 0.75))
    b = max(0, vehicles - a)
    c = max(1, math.ceil(vehicles * 0.5))
    shifts = [{"start": "05:30", "end": "14:00", "count": a}, {"start": "14:00", "end": "22:00", "count": min(c, a)}]
    if b:
        shifts.append({"start": "09:15", "end": "17:45", "count": b})
    wk = ["06:00", "21:00"]
    raw = {
        "id": "proposal",
        "name": inp.name,
        "type": "city",
        "region": {"state": inp.state, "jurisdiction": inp.jurisdiction or inp.name},
        "timezone": inp.timezone,
        "phase": 1,
        "modes": modes,
        "zones": zones,
        "service_hours": {"mon": wk, "tue": wk, "wed": wk, "thu": wk, "fri": wk, "sat": ["08:00", "18:00"], "sun": None},
        "fares": {m: {"base": 2.0} for m in modes},
        "booking_rules": {
            **({"paratransit": {}} if "paratransit" in modes else {}),
            **({"microtransit": {"max_wait_min": 30}} if "microtransit" in modes else {}),
        },
        "ada_rules": {"fixed_route_fare": 2.0} if "paratransit" in modes else None,
        "fleet": [{"adapter": "human_driver", "count": vehicles, "seats": 8, "wheelchair_positions": 1, "prefix": "P"}],
        "shifts": shifts,
        "depot": list(depot),
        "funding_sources": [{"id": "general", "type": "city"}],
        "branding": {"display_name": inp.name},
        "contacts": {"city_program_manager": "tbd", "insurer": "tbd"},
    }
    return raw


def _simulate(inp: ProposalInput, vehicles: int, spec: DemandSpec) -> dict[str, Any]:
    from ..platform import Platform
    from ..sim.runner import simulate_day

    day = date(2027, 3, 2)  # a Tuesday: representative weekday
    p = Platform(today=day - timedelta(days=1))
    p.provision(config_from_dict(_synthetic_config(inp, vehicles)))
    res = simulate_day(p, day, {"proposal": spec}, SimParams(), seed=inp.seed)
    return res.tenants["proposal"]


def check_jurisdiction(inp: ProposalInput) -> None:
    for ex in load_policy().get("excluded_jurisdictions", []):
        if inp.state.upper() == ex["state"].upper() and (inp.jurisdiction or inp.name).lower().startswith(ex["jurisdiction"].lower()):
            raise PermissionError(f"Roam does not propose in {ex['jurisdiction']}: {ex['reason']}")


def generate_proposal(inp: ProposalInput, cost_model: dict | None = None) -> dict[str, Any]:
    check_jurisdiction(inp)
    cm = cost_model or load_cost_model()
    area = geo.area_km2(inp.boundary)
    cells = geo.h3_cells_for(inp.boundary, 8)
    pop_assumed = inp.population is None
    population = inp.population or int(area * inp.density_per_km2)

    para_full = population * inp.paratransit_trips_per_capita_day if "paratransit" in inp.modes else 0.0
    micro_full = population * inp.microtransit_trips_per_capita_day if "microtransit" in inp.modes else 0.0
    para_s = min(inp.sample_cap, round(para_full)) if para_full else 0
    micro_s = min(inp.sample_cap, round(micro_full)) if micro_full else 0
    sample_trips = max(1, para_s + micro_s)
    spec = DemandSpec(paratransit_trips=para_s, microtransit_trips=micro_s)

    # ---- fleet sizing on the sample day: smallest fleet with zero ADA denials, OTP >= 90%,
    # and <= 10% microtransit requests unserved (grow geometrically, then bisect down)
    def passes(kk: dict) -> bool:
        unserved = kk["microtransit_unserved"] / micro_s if micro_s else 0.0
        return kk["ada_denials"] == 0 and kk["on_time_performance"] >= 0.90 and unserved <= 0.10

    history: list[dict] = []
    results: dict[int, dict] = {}

    def run(n: int) -> dict:
        if n not in results:
            kk = _simulate(inp, n, spec)
            results[n] = kk
            history.append(
                {
                    "vehicles": n,
                    "ada_denials": kk["ada_denials"],
                    "otp": kk["on_time_performance"],
                    "micro_unserved": kk["microtransit_unserved"],
                }
            )
        return results[n]

    lo, hi = 1, max(2, math.ceil(sample_trips / 20))
    while not passes(run(hi)) and hi < 400:
        lo, hi = hi, math.ceil(hi * 1.5)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if passes(run(mid)):
            hi = mid
        else:
            lo = mid
    n = hi
    k = run(n)

    # ---- scale sample -> full weekday, then annualise
    full_trips_day = para_full + micro_full
    scale = full_trips_day / sample_trips if sample_trips else 1.0
    served_share = k["trips_completed"] / max(1, k["trips_requested"])
    vrh_day = k["vehicle_revenue_hours"] * scale
    km_day = k["vehicle_total_km"] * scale
    fleet = max(2, math.ceil(n * scale * 1.15))  # +15% spare ratio
    days = WEEKDAYS_PER_YEAR + SATURDAY_EQUIV
    trips_year = full_trips_day * served_share * days
    ops = Operations(
        vehicles=fleet,
        revenue_hours=vrh_day * days,
        revenue_km=k["vehicle_revenue_km"] * scale * days,
        total_km=km_day * days,
        trips=round(trips_year),
        service_days=days,
        months=12,
        wheelchair_trips=round(trips_year * 0.2 * (para_full / max(1.0, full_trips_day))),
    )
    phases = {f"phase_{p}": phase_cost(p, ops, cm) for p in (1, 2, 3)}
    bench = turnkey_benchmark(ops, cm)
    # sensitivity: AV software licence fee at which driverless matches human-driven cost
    lic = cm["phase3"]["av_software_license_per_vehicle_month"]
    gap = phases["phase_3"]["total"] - phases["phase_1"]["total"]
    breakeven_license = lic - gap / (ops.vehicles * ops.months)
    current = None
    if inp.current_annual_cost:
        current = {
            "annual_cost": inp.current_annual_cost,
            "cost_per_trip": inp.current_annual_cost / inp.current_annual_trips if inp.current_annual_trips else None,
        }
    return {
        "city": inp.name,
        "state": inp.state,
        "inputs": {
            "area_km2": round(area, 1),
            "h3_res8_cells": len(cells),
            "population": population,
            "population_assumed_from_density": pop_assumed,
            "modes": list(inp.modes),
        },
        "demand": {
            "paratransit_trips_per_weekday": round(para_full),
            "microtransit_trips_per_weekday": round(micro_full),
            "sample_day": {"paratransit": para_s, "microtransit": micro_s, "scale_factor": round(scale, 2)},
        },
        "service_design": {
            "fleet_size": fleet,
            "wheelchair_positions": fleet,
            "service_hours": "Mon-Fri 06:00-21:00, Sat 08:00-18:00",
            "zones": ["paratransit: full boundary (ADA)"] * ("paratransit" in inp.modes)
            + ["microtransit: on-demand zone"] * ("microtransit" in inp.modes),
            "annual_vehicle_revenue_hours": round(ops.revenue_hours),
            "annual_trips": round(trips_year),
        },
        "simulation": {"sizing_history": history, "kpis_sample_day": k},
        "costs": {name: {kk: round(v, 2) for kk, v in c.items()} for name, c in phases.items()},
        "benchmark": {kk: round(v, 2) for kk, v in bench.items()} | {"source": cm["benchmarks"]["turnkey_vrh_source"]},
        "sensitivity": {
            "av_license_assumed_per_vehicle_month": lic,
            "av_license_breakeven_per_vehicle_month": round(breakeven_license, 0),
            "phase3_vs_phase1_savings": round(-gap, 0),
        },
        "current": current,
        "assumptions": [
            "Travel times use a haversine model (no road network); VERIFY with OSRM/Valhalla.",
            "Demand rates per capita are planning assumptions; replace with agency ridership data.",
            *(["Population estimated from area x default density; replace with Census/ACS."] if pop_assumed else []),
            "Cost inputs are PLACEHOLDERS in roam/config/cost_model.yaml; replace with local quotes.",
            "AV phase costs depend on provider fleet APIs and per-vehicle fees (VERIFY).",
            "Fleet scales linearly from a sampled day; real density usually raises productivity (conservative).",
            *inp.notes,
        ],
    }


# ------------------------------------------------------------------ PDF
def write_pdf(proposal: dict[str, Any], path: str | Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ss = getSampleStyleSheet()
    small = ss["BodyText"].clone("small", fontSize=7.5, leading=9)
    doc = SimpleDocTemplate(
        str(path), pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch, topMargin=0.5 * inch, bottomMargin=0.5 * inch
    )
    sd, c, b = proposal["service_design"], proposal["costs"], proposal["benchmark"]
    money = lambda v: f"${v:,.0f}"  # noqa: E731
    millions = lambda v: f"${v / 1e6:,.2f}M"  # noqa: E731
    story = [
        Paragraph(f"Roam Transit OS: own your transit network. {proposal['city']}", ss["Title"]),
        Paragraph(
            f"Service design for a city-owned on-demand network ({', '.join(proposal['inputs']['modes'])}). "
            f"Area {proposal['inputs']['area_km2']} km&sup2;, population {proposal['inputs']['population']:,}"
            f"{' (estimated)' if proposal['inputs']['population_assumed_from_density'] else ''}.",
            ss["BodyText"],
        ),
        Spacer(1, 6),
    ]
    design = [
        ["Fleet (incl. 15% spares)", f"{sd['fleet_size']} accessible vehicles"],
        ["Service hours", sd["service_hours"]],
        [
            "Weekday demand",
            f"{proposal['demand']['paratransit_trips_per_weekday']} paratransit + "
            f"{proposal['demand']['microtransit_trips_per_weekday']} microtransit trips",
        ],
        ["Annual vehicle revenue hours", f"{sd['annual_vehicle_revenue_hours']:,}"],
        ["Annual trips", f"{sd['annual_trips']:,}"],
    ]
    t1 = Table(design, colWidths=[2.4 * inch, 4.6 * inch])
    t1.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
            ]
        )
    )
    story += [Paragraph("Service design", ss["Heading3"]), t1, Spacer(1, 8)]

    rows = [["", "Turnkey (benchmark)", "Phase 1: human-driven", "Phase 2: hybrid AV", "Phase 3: driverless"]]
    rows.append(
        [
            "Annual program cost",
            f"{millions(b['turnkey_low'])}-{millions(b['turnkey_high'])}",
            millions(c["phase_1"]["total"]),
            millions(c["phase_2"]["total"]),
            millions(c["phase_3"]["total"]),
        ]
    )
    rows.append(
        [
            "Cost per trip",
            f"{money(b['turnkey_cost_per_trip_low'])}-{money(b['turnkey_cost_per_trip_high'])}",
            money(c["phase_1"]["cost_per_trip"]),
            money(c["phase_2"]["cost_per_trip"]),
            money(c["phase_3"]["cost_per_trip"]),
        ]
    )
    rows.append(
        [
            "Cost per revenue hour",
            "$65-$90",
            money(c["phase_1"]["cost_per_vrh"]),
            money(c["phase_2"]["cost_per_vrh"]),
            money(c["phase_3"]["cost_per_vrh"]),
        ]
    )
    rows.append(["City owns fleet & data", "No", "Yes", "Yes", "Yes"])
    t2 = Table(rows, colWidths=[1.6 * inch, 1.45 * inch, 1.35 * inch, 1.3 * inch, 1.3 * inch])
    t2.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b57")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (0, -1), colors.whitesmoke),
            ]
        )
    )
    story += [Paragraph("Three-phase cost comparison", ss["Heading3"]), t2, Spacer(1, 6)]

    p1 = c["phase_1"]
    lines = [k for k in ("drivers", "vehicle_leases", "insurance", "energy_maintenance", "roam_platform_fee", "roam_ops_fee") if k in p1]
    story.append(
        Paragraph(
            "Phase 1 cost lines: "
            + "; ".join(f"{k.replace('_', ' ')} {money(p1[k])}" for k in lines)
            + f". Roam's share of program cost: {p1['roam_take_share'] * 100:.0f}%.",
            small,
        )
    )
    p3 = c["phase_3"]
    story.append(
        Paragraph(
            "Phase 3 still budgets labor: "
            + "; ".join(
                f"{k.replace('_', ' ')} {money(p3[k])}"
                for k in ("remote_supervision", "field_technicians", "cleaning", "av_software_licenses", "accessibility_attendants")
                if k in p3
            )
            + ".",
            small,
        )
    )
    sens = proposal["sensitivity"]
    story.append(
        Paragraph(
            f"Sensitivity: driverless beats human-driven only if the AV software licence is below "
            f"{money(sens['av_license_breakeven_per_vehicle_month'])} per vehicle-month "
            f"(assumed {money(sens['av_license_assumed_per_vehicle_month'])}).",
            small,
        )
    )
    if proposal.get("current"):
        cur = proposal["current"]
        story.append(
            Paragraph(
                f"Current program: {money(cur['annual_cost'])} per year"
                + (f", {money(cur['cost_per_trip'])} per trip." if cur.get("cost_per_trip") else "."),
                small,
            )
        )
    story += [Spacer(1, 6), Paragraph("Assumptions and items to verify", ss["Heading4"])]
    for a in proposal["assumptions"]:
        story.append(Paragraph("&bull; " + a, small))
    story.append(Paragraph("Benchmark: " + proposal["benchmark"]["source"], small))
    doc.build(story)
    return path
