"""Command line: ``roam validate | golive | simulate | propose | serve``."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path


def _next_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def cmd_validate(a) -> int:
    from .config.schema import load_config
    from .config.validate import validate

    cfg, geoms = load_config(a.config)
    rep = validate(cfg, geoms)
    print(json.dumps(rep.as_dict(), indent=2))
    return 0 if rep.ok else 1


def cmd_golive(a) -> int:
    """Provision a tenant from config and prove it can take a trip end to end."""
    from .exports.gtfs_flex import write_gtfs_flex_zip
    from .platform import Platform, ProvisioningError

    t0 = time.perf_counter()
    p = Platform()
    try:
        rt = p.provision(a.config, require_go_live=not a.simulation_only)
    except ProvisioningError as e:
        print(json.dumps(e.report.as_dict(), indent=2))
        print("NOT LIVE: fix the errors / go-live blockers above (use --simulation-only to provision for simulation).")
        return 1
    out = Path(a.out) / rt.id
    gtfs = write_gtfs_flex_zip(rt, out / "gtfs_flex.zip")
    print(
        json.dumps(
            {
                "tenant": rt.id,
                "zones": len(rt.zones),
                "vehicles": len(rt.vehicles),
                "validation": rt.validation.as_dict(),
                "gtfs_flex": str(gtfs),
                "seconds": round(time.perf_counter() - t0, 2),
            },
            indent=2,
        )
    )
    return 0


def cmd_simulate(a) -> int:
    from .platform import Platform
    from .sim.demand import DemandSpec
    from .sim.runner import simulate_day

    day = _next_weekday(date.fromisoformat(a.date) if a.date else date.today() + timedelta(days=1))
    p = Platform(today=day - timedelta(days=1))
    specs = {}
    for cfg in a.config:
        rt = p.provision(cfg)
        specs[rt.id] = DemandSpec(paratransit_trips=a.paratransit, microtransit_trips=a.microtransit, av_trips=a.av)
    p.ops.add_seat("seat-1", "Ops seat 1", set(specs))
    t0 = time.perf_counter()
    res = simulate_day(p, day, specs, seed=a.seed)
    seat = p.ops.simulate_seat("seat-1", 5 * 60, 23 * 60, day)
    print(
        json.dumps(
            {
                "service_date": day.isoformat(),
                "kpis": res.tenants,
                "batch": res.batch,
                "ops_seat": seat,
                "seconds": round(time.perf_counter() - t0, 1),
            },
            indent=2,
            default=str,
        )
    )
    return 0


def cmd_propose(a) -> int:
    from .config.schema import load_config
    from .proposal.generator import ProposalInput, generate_proposal, slug, write_pdf

    if a.config:
        cfg, geoms = load_config(a.config)
        zones = {z.mode.value: geoms[z.id] for z in cfg.zones}
        boundary = zones.get("paratransit") or zones.get("microtransit") or next(iter(geoms.values()))
        inp = ProposalInput(
            name=cfg.name,
            state=cfg.region.get("state", ""),
            jurisdiction=cfg.region.get("jurisdiction"),
            boundary=boundary,
            population=a.population,
            microtransit_boundary=zones.get("microtransit"),
            depot=tuple(cfg.depot),
            timezone=cfg.timezone,
            modes=tuple(m for m in ("paratransit", "microtransit") if m in zones) or ("microtransit",),
            current_annual_cost=a.current_cost,
            current_annual_trips=a.current_trips,
        )
    else:
        g = json.loads(Path(a.boundary).read_text())
        if g.get("type") == "FeatureCollection":
            g = g["features"][0]["geometry"]
        elif g.get("type") == "Feature":
            g = g["geometry"]
        inp = ProposalInput(
            name=a.name,
            state=a.state,
            boundary=g,
            population=a.population,
            current_annual_cost=a.current_cost,
            current_annual_trips=a.current_trips,
        )
    prop = generate_proposal(inp)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = slug(inp.name)
    (out / f"{stem}_proposal.json").write_text(json.dumps(prop, indent=2, default=str))
    pdf = write_pdf(prop, out / f"{stem}_proposal.pdf")
    summary = {ph: {k: prop["costs"][ph][k] for k in ("total", "cost_per_trip", "cost_per_vrh", "roam_take_share")} for ph in prop["costs"]}
    print(
        json.dumps(
            {
                "service_design": prop["service_design"],
                "costs": summary,
                "benchmark": prop["benchmark"],
                "sensitivity": prop["sensitivity"],
                "pdf": str(pdf),
            },
            indent=2,
        )
    )
    return 0


def cmd_serve(a) -> int:  # pragma: no cover - interactive
    import secrets

    import uvicorn

    from .api import Principal, create_app
    from .platform import Platform

    p = Platform()
    tenants = [p.provision(c).id for c in a.config]
    keys = {secrets.token_urlsafe(12): Principal("ops", None, "seat-1")}
    for t in tenants:
        keys[secrets.token_urlsafe(12)] = Principal("city", {t})
    p.ops.add_seat("seat-1", "Ops seat 1", set(tenants))
    for k, pr in keys.items():
        print(f"API key {k}: role={pr.role} tenants={sorted(pr.tenant_ids) if pr.tenant_ids else 'ALL'}")
    uvicorn.run(create_app(p, keys), host=a.host, port=a.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="roam", description="Roam Transit OS (MVP v0.1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("validate", help="validate a tenant config")
    s.add_argument("config")
    s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("golive", help="provision a tenant from config")
    s.add_argument("config")
    s.add_argument("--out", default="out")
    s.add_argument("--simulation-only", action="store_true", help="ignore go-live blockers (simulation/proposal use)")
    s.set_defaults(fn=cmd_golive)
    s = sub.add_parser("simulate", help="simulate a service day for one or more tenants on one ops seat")
    s.add_argument("config", nargs="+")
    s.add_argument("--date")
    s.add_argument("--paratransit", type=int, default=60)
    s.add_argument("--microtransit", type=int, default=40)
    s.add_argument("--av", type=int, default=15)
    s.add_argument("--seed", type=int, default=11)
    s.set_defaults(fn=cmd_simulate)
    s = sub.add_parser("propose", help="generate a three-phase proposal (JSON + one-page PDF)")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--config", help="use a tenant config's zones as the boundary")
    g.add_argument("--boundary", help="GeoJSON boundary file")
    s.add_argument("--name", default="City")
    s.add_argument("--state", default="")
    s.add_argument("--population", type=int)
    s.add_argument("--current-cost", type=float)
    s.add_argument("--current-trips", type=float)
    s.add_argument("--out", default="out/proposals")
    s.set_defaults(fn=cmd_propose)
    s = sub.add_parser("serve", help="run the API + ops console")
    s.add_argument("config", nargs="*")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
