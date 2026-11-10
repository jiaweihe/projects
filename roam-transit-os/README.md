# Roam Transit OS: MVP v0.1

A multi-tenant operations layer that lets a city, county or community **own** its on-demand transit network: ADA paratransit, microtransit, and AV networks behind one vehicle-adapter interface. This is the v0.1 build of the spec dated 2026-11-10 (Roam Mobility, Inc.; not a CARTS project).

Python 3.11+, FastAPI, pydantic. The core needs no database or routing server. OR-Tools and H3 are optional and used when installed.

```bash
pip install -e ".[dev,routing,geo]"
pytest -q                                   # 51 tests, ~15 s, including the four v0.1 acceptance tests

roam validate tenants/mercer_county_nj.yaml
roam golive   tenants/austin_tx.yaml --simulation-only   # provision a city from one config file
                                            # (copy tenants/_template.yaml for a new city)
roam simulate tenants/mercer_county_nj.yaml tenants/austin_tx.yaml tenants/miami_dade_fl.yaml
roam propose  --config tenants/mercer_county_nj.yaml --population 387340   # JSON + one-page PDF
roam serve    tenants/*.yaml                # API + ops console at http://127.0.0.1:8000
```

## v0.1 build order (spec §13): status

| # | Item | Status | Where |
|---|---|---|---|
| 1 | Tenant config, zones, policies, multi-tenant data model | Done | `roam/config/`, `roam/models.py`, `roam/store.py`, `db/schema.sql` |
| 2 | Simulator adapter + synthetic demand | Done | `roam/adapters/simulator.py`, `roam/sim/` |
| 3 | Booking + batch and real-time dispatch | Done (insertion heuristic default; OR-Tools optional) | `roam/booking.py`, `roam/dispatch/` |
| 4 | Driver app (human_driver adapter) | Server side done: manifest, stop actions, securement checklist. No React Native app yet | `roam/adapters/human_driver.py`, `/driver/*` API |
| 5 | Ops console, multi-tenant exceptions queue | Done: queue, seats, load metric, incidents, minimal web UI | `roam/ops/`, `roam/web/console.html` |
| 6 | City dashboard: KPIs + invoices | API done (all §9 KPIs, invoice = platform + hours + performance). No React dashboard yet | `roam/kpi.py`, `roam/billing.py` |
| 7 | Phone/IVR booking, AI agent + human fallback | Done: keypad + speech state machine, Twilio TwiML webhook, pluggable `BookingAgent`. Rule-based agent; LLM agent not wired | `roam/ivr.py` |
| 8 | GTFS-Flex / GTFS-Realtime / MDS exports | Done; plus NTD template and full raw export | `roam/exports/` |
| 9 | Proposal generator (PDF) | Done | `roam/proposal/generator.py` |
| 10 | `av_partner` adapter stub against the simulator | Done: ODD enforcement, remote-assist to ops queue | `roam/adapters/av_partner.py` |

## Acceptance tests (`tests/test_acceptance.py`)

| Spec test | Result |
|---|---|
| New tenant goes live from config in under one day of setup | A fresh tenant (`testville`) is validated, provisioned, publishes GTFS-Flex and runs a full simulated day in a few seconds. The human work is one YAML file plus a zone GeoJSON. |
| Simulated paratransit day: zero capacity denials, OTP > 90% | Mercer fixture, 60 paratransit trips/day, 5 seeds: 0 denials, OTP 98–100%, every trip closed out. |
| One ops seat supervises 3+ tenants | One seat, 3 tenants, 30 vehicles, plus injected remote-assist and fault exceptions: seat utilization about 3%, and every exception picked up within a minute. |
| Proposal generator: three-phase comparison for any fixture | All three fixtures produce phase 1/2/3 costs, the turnkey benchmark, an AV-licence sensitivity, and a PDF. |

### Snapshot: proposal outputs (placeholder cost inputs)

| Fixture | Fleet | Annual VRH | Turnkey ($65–90/VRH) | Phase 1 | Phase 2 | Phase 3 | AV licence break-even |
|---|---|---|---|---|---|---|---|
| Mercer County, NJ (pop. 387,340) | 81 | 193,587 | $12.58M–$17.42M | $14.16M ($73/VRH) | $14.28M | $14.56M | $3,596/veh-month |
| Austin, TX (East zone, pop. estimated) | 4 | 9,438 | $0.61M–$0.85M | $0.68M ($72/VRH) | $0.69M | $0.70M | $3,531/veh-month |
| Miami-Dade, FL (core, pop. estimated) | 145 | 289,812 | $18.84M–$26.08M | $22.77M ($79/VRH) | $23.46M | $25.07M | $2,682/veh-month |

**Read this before using these numbers in a pitch:**
- Phase 1 lands inside the turnkey band and below Via's documented $89/VRH. Roam's take is about 18% of program cost, inside the 15–20% target.
- **With the placeholder AV inputs, phase 3 is not cheaper than phase 1.** The assumptions are a $4,000/vehicle-month AV software licence, $3,500 AV lease, remote supervision, field techs, cleaning and attendants. The proposal reports the licence fee at which driverless breaks even, about $2.7K–3.6K/vehicle-month for these fixtures. The "much lower" claim for phase 3 (spec §2.4) depends on that number, so it is the first thing to verify with AV providers.
- Every cost input lives in `roam/config/cost_model.yaml` and is marked PLACEHOLDER, except the cited benchmarks.

## How it works

```
tenant.yaml + zones.geojson
        │  validate (errors / go-live blockers / warnings) → provision (Tenant, ServiceZone+H3, ServicePolicy, Vehicles, Funding)
        ▼
Booking (app · web · IVR · agent) ── paratransit: next-day, ±60 min negotiation, eligibility, standing orders
        │                            microtransit: real-time, walk-to-stop, GTFS transfer
        ▼
Dispatcher (per tenant per day) ── insert → repair (move one booked trip) → denial only if both fail (logged + alerted)
        │  batch re-optimisation before the day (insertion+relocate, or OR-Tools), keeps the plan only if all promises hold
        ▼
VehicleAdapter ── human_driver (driver app) · av_partner (provider API, ODD-checked) · simulator
        │  events: en_route · arrival · boarding · no_show · dropoff · fault · remote_assist
        ▼
Ops center (one seat, many tenants) · KPIs · invoices · GTFS-Flex/RT · MDS · NTD · raw export
```

Design choices worth knowing:
- **Tenant isolation everywhere.** Every row carries `tenant_id`. `TenantScope` cannot read or write across tenants, and only an `OpsScope` (a Roam seat) spans them. The API returns 404, not 403, for other tenants so it never confirms they exist. Production uses Postgres RLS (`db/schema.sql`).
- **No silent denials.** Paratransit booking tries insertion at the requested time and each negotiation offset, then a repair move, before it records a denial. A denial always writes an `ada_denial` event and an ops exception. It also forfeits the performance bonus on the invoice.
- **Guardrails from spec §3 are code.** `roam/config/policy.yaml` hard-excludes Jersey City; validation, provisioning and the proposal generator all refuse it. Mercer County provisions for simulation but is **blocked from go-live** until MOVES ownership is resolved. AV fleets are go-live-blocked without a state AV authorization profile. Federal funds plus AV adds a Section 13(c) blocker.
- **Pricing follows the spec.** The invoice is a platform fee per vehicle-month, plus an ops fee per revenue hour, plus a performance adjustment capped at ±10%. It is not a percentage of budget.
- **The city owns the data.** `exports/raw.py` dumps every table (CSV, plus Parquet if pyarrow is installed). Rider PII is excluded unless the city itself asks.

## Layout

```
roam/
  models.py            data model (spec §8)
  config/              tenant schema, validation, Roam guardrails, cost model
  tenancy.py store.py  tenant runtime, multi-tenant store
  booking.py           booking rules for every channel
  dispatch/            Task/Unit/evaluate core, insertion solver, OR-Tools solver, dispatcher
  adapters/            VehicleAdapter interface + human_driver, av_partner, simulator
  sim/                 discrete-event world, synthetic demand, day runner
  ops/                 exceptions queue, seats, load, incident workflow
  kpi.py costing.py billing.py
  exports/             gtfs_flex, gtfs_realtime, mds, ntd, raw, gtfs_import
  proposal/            proposal generator + PDF
  ivr.py api.py cli.py web/console.html
tenants/               fixtures (Mercer, Austin, Miami-Dade), template, zone GeoJSON
db/schema.sql          Postgres/PostGIS/H3 target schema with RLS
tests/                 unit + API + acceptance tests
```

## Placeholders and items to verify

- **Zone polygons** in `tenants/zones/` are rough outlines for simulation. Replace them with official boundaries.
- **Travel times** use a haversine model whose speed rises with distance. Load OSRM or Valhalla (`geo.OSRMTravelModel`) before go-live; validation keeps this as a go-live blocker.
- **Fares**: NJ TRANSIT, CapMetro and Metrobus fixed-route fares are marked VERIFY. The ADA 2× fare cap is enforced against them.
- **Fleet sizes and shifts** in the fixtures are placeholders. Mercer's 8 vans serve about 60 paratransit trips/day with zero denials in simulation. Above roughly 70, the morning peak needs more vehicles.
- **Field names**: MDS (`passenger-services` mode, event names, `trip_type` vocabulary), the GTFS-Flex fields and the NTD demand-response form fields are all marked VERIFY in code.
- **IVR**: Twilio signature validation is a TODO. The AI booking agent is a rule-based stand-in behind the `BookingAgent` protocol.
- **Demand rates** per capita in the proposal generator are planning assumptions. When population is not given, it is estimated from area × density.
- **Open spec questions** (§14) are unchanged: open-core licence, MOVES ownership, AV provider APIs and fees, insurance pool structure, cooperative purchasing.

## Known limitations (next steps)

- In simulation, OTP is optimistic. Noise is per-leg travel variance only; there are no incidents, dwell variance or late drivers. Calibrate against pilot data.
- Proposals scale a sampled day linearly to full demand. That is conservative, because real density raises productivity.
- No persistence yet: the store is in memory, and the Postgres schema is written but not wired.
- No React ops console, city dashboard, or React Native rider/driver apps yet. The API and a minimal HTML console cover the flows.
- Insurance pool tooling (§7.9), institutional portal and Medicaid NEMT are v0.2.
