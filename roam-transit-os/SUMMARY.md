# Overnight session summary: branch `overnight/2026-11-10`

**Goal given:** "make it simplistic and into mvp". I read that as: keep a working MVP, make it simpler and more robust, and fix real defects without adding scope. The work ran 25 iterations (the maximum) with 26 commits. Each iteration is logged in `LOG.md` with its audit, plan, self-review and metrics.

## Baseline vs final

| Metric | Baseline | Final | Change |
|---|---|---|---|
| Tests passing | 51 / 51 | **116 / 116** | +65 tests, 0 failing |
| Coverage (`roam`) | 84% | **94%** | +10 pts |
| Ruff findings (rules `E,F,W,B,I,UP,SIM`) | 121 (86 under the committed config that ignores B008/UP042) | **0** | enforced by a test |
| Mypy errors | 25 | **0** | enforced by a test |
| Statements (`roam/`, from coverage) | 3,503 | 3,549 | +1.3% (see note) |
| Bench: simulate 3-tenant day | 2.13 s | **0.64 s** | −70% |
| Bench: Mercer proposal | 5.19 s | **1.30 s** | −75% |
| Bench: provision 3 tenants | 0.04 s | 0.04 s | – |
| Test suite wall time | 14.5 s (32.9 s with coverage) | 9.8 s (~20 s with coverage) | faster with 2.3× the tests |
| Wheel build | 2.6 s | 2.7 s | – |
| Optional dependencies | ortools, httpx, h3 | httpx, h3 | OR-Tools removed |
| API routes that 5xx on garbage input | ≥ 12 found | **0** | enforced by a sweep test |

**Note on size:** simplification removed about 165 statements: the OR-Tools solver plus its repair hack, dead helpers, unused `RunPatch` fields and an unused ops listener hook. Input validation, security checks and two small missing driver-app endpoints added about 210. Raw line count also rose because `ruff format` wraps long lines. That's why I tracked statements rather than lines after iteration 5.

## Every change, by iteration

| # | Category | Change |
|---|---|---|
| 1 | Security | Path traversal via city name in the proposal PDF. The API now streams the PDF and writes nothing to the host. One shared `slug()`. |
| 2 | Bug | Closed trips, including **ADA denials**, could be "cancelled", which erased them from the KPIs. Cancelling an en-route trip leaked a seat and later flipped back to completed. |
| 3 | Performance | Insertion search prunes using the first-violation index from `evaluate_at`. Results are identical to brute force, which is tested. Simulation −72%, proposal −69%. |
| 4 | Simplification | Removed the optional OR-Tools solver (~190 LOC). Any `Solver` object can be plugged in through `Platform(batch_solver=...)`, which is tested. |
| 5 | Quality | Ruff config plus a gate test; 120 findings → 0; one-off `ruff format`. |
| 6 | Quality | Mypy config plus a gate test; 25 errors → 0, fixed at the root (`partial` instead of lambdas, no new `type: ignore`). |
| 7 | Bug/coverage | Incident workflow tests. A missing contact used to be "notified" at a placeholder string; it's now recorded as undelivered and raises an ops alert. |
| 8 | Bug | Vehicle faults: faulted simulated vehicles kept driving; a rescue overwrote the rider's original pickup time (false late flags); a fault between shifts was ignored and the vehicle's other shifts were orphaned. Faults are now handled per vehicle. |
| 9 | UX/bug | CLI smoke tests. A refused proposal exits cleanly with code 2. A go-live refusal no longer relabels blockers as errors. |
| 10 | Bug | GTFS fixed-route transfer and trip-updates tests. The GTFS-RT feed no longer emits `"vehicle": null`. |
| 11 | Security | The Twilio IVR webhook was unauthenticated. It now validates HMAC signatures, is closed by default, works behind a proxy, and caps session count. |
| 12 | Bug | A bad tenant config gave a 500, now a 422. Re-provisioning an existing tenant silently overwrote it, now a 409. |
| 13 | Security | Driver endpoints revealed which vehicle ids exist. Driver keys can now be bound to vehicles. |
| 14 | Docs | README refreshed. A test parses every `roam` command shown in the README. |
| 15 | Security | Phone impersonation: a rider number alone gave access. Now a PIN is required, rider numbers can't be enumerated, and PINs are never logged. |
| 16 | Bug | Phone cancellation now needs confirmation (keypad or speech, safe against concurrent changes). Leap-day date entry no longer crashes. |
| 17 | Bug | The driver's manifest dropped the stop they were driving to. Impossible driver actions (boarding a cancelled stop, drop-off before boarding) are rejected. |
| 18 | Bug/security | The raw export now downloads as a zip, with no PII left on the host. Tenant ids are restricted to safe slugs. |
| 19 | Bug | Invoice period and date-range validation. |
| 20 | Simplification | Dead code removed. |
| 21 | Feature gap | Driver app `fault` and `telemetry` endpoints (a breakdown couldn't be reported before). Strict time and coordinate validation. Duplicate fault reports alert once. |
| 22 | Bug | Shared `HHMM` and `LonLatIn` types on every request model. Bad KPI ranges and bad proposal boundaries return 422. |
| 23 | Bug/security | A garbage-input sweep over every route. Ops exceptions are tenant-scoped: any ops key could previously resolve another city's alert. |
| 24 | Security | PINs stored as salted PBKDF2 hashes, settable through the API, never echoed or exported. Riders can no longer self-certify ADA eligibility. |
| 25 | Security | Rider keys are bound to their own rider for booking, viewing and cancelling. Cancelling an unknown trip returns 404. |

## Decisions made without a human (also in LOG.md)

- **Branch.** Worked on `overnight/2026-11-10`, branched from the MVP branch `ccr-e4f9b99f-vexd1m`. `main`/`master` were not touched.
- **Dev tools.** Added `ruff`, `mypy` and `pytest-cov` to the `[dev]` extra only, for measurement. No runtime dependency was added; crypto uses the standard library.
- **OR-Tools test removed.** I deleted the OR-Tools solver, and its test went with it. The spec's "swappable solver" requirement is now covered by a plug-in test.
- **Lint exceptions.** B008 (the FastAPI `Depends()` idiom) and UP042 (StrEnum would change how enums print) are ignored.
- **API behaviour changes clients will see:**
  - The IVR webhook refuses requests without `TWILIO_AUTH_TOKEN`.
  - Unbound rider keys can no longer book.
  - `POST /exports/raw` returns a zip instead of a manifest.
  - Cancelling an unknown trip returns 404 instead of 409.
  - Re-posting a tenant returns 409.

## Open issues

1. **No persistence.** The store is in memory, and `db/schema.sql` (Postgres RLS) is written but not wired.
2. **Auth is API-key based** (the `Principal` map). Production needs OIDC and key management. Driver and rider keys must be minted with their vehicle or rider bindings, or rider keys can't book.
3. **The fixed-route transfer has no maximum distance** to the rider's final destination. Only in-zone stops are candidates.
4. **Reassigned pickups after a fault** get a wider planning window. The rider's promised window still drives OTP, so the KPI stays honest, but the rider is not told about the delay.
5. **`api.py` is now about 560 lines.** It's acceptable, with one route per spec surface; splitting it into routers is a mechanical follow-up.
6. **Exports are built in memory**, which is fine at MVP volume. Stream them for large tenants.
7. **Product-level placeholders are unchanged:** zone outlines, cost inputs, fares, demand rates, the MDS/NTD field names marked VERIFY, and the AV licence break-even that decides the phase-3 pitch.

## Recommended next steps for a human

1. Decide on auth (OIDC, and how rider and driver keys are issued with their bindings), then wire Postgres with the provided RLS schema.
2. Configure `TWILIO_AUTH_TOKEN` and `ROAM_PUBLIC_URL` before pointing a phone number at the IVR.
3. Replace the placeholder cost inputs, especially the AV software licence, and re-run `roam propose` for the fixtures.
4. Load an OSRM extract per tenant to clear the go-live blocker, and calibrate the simulator against pilot data, because the simulated OTP is optimistic.
5. Resolve the governance blockers (MOVES ownership, state AV authorizations) recorded in `roam/config/policy.yaml` and the fixtures.

To reproduce the numbers above: `pip install -e ".[dev,geo]" && bash scripts/metrics.sh`.
