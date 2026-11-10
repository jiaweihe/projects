# Overnight log — branch `overnight/2026-11-10`

Goal (from the human): "make it simplistic and into mvp" — simplify the codebase while
keeping it a working MVP. Interpreted as: fewer moving parts and lines, fewer
lint/type errors, no regressions in behaviour, fix real bugs/security issues found
along the way, keep every acceptance test.

## Decisions taken without a human
- Branch `overnight/2026-11-10` created from `ccr-e4f9b99f-vexd1m` (the MVP branch; `main`/`master` untouched).
- Dev-only tools added for measurement: `ruff`, `mypy`, `pytest-cov` (not runtime deps; added to `[dev]` extra).
- Lint rule set: `E,F,W,B,I,UP,SIM`, line length 140. Type check: `mypy roam --ignore-missing-imports`.
- Metrics script: `scripts/metrics.sh` (tests, coverage, ruff count, mypy count, non-comment LOC, benchmarks, wheel build time).
- Benchmarks: provision 3 fixtures; simulate one day for 3 tenants (seed 7); Mercer proposal (sample_cap 70).

## Baseline (before any change)
| Metric | Value |
|---|---|
| Tests | 51/51 pass (100%) |
| Coverage (`roam`) | 84% (3503 stmts, 551 missed) |
| Ruff findings | 121 |
| Mypy errors | 25 |
| Non-comment LOC in `roam/` | 4544 |
| Bench: provision 3 tenants | 0.04 s |
| Bench: simulate 3-tenant day | 2.13 s |
| Bench: Mercer proposal | 5.19 s |
| Wheel build | 2.6 s |
| Test suite wall time (with coverage) | 32.9 s |

## Iteration 1 — path traversal in proposal PDF filename (security)
**Audit (top 5):** (1) `/proposals?pdf=1` builds a file path from the user-supplied city name → path traversal + files left on the API host; (2) IVR offer crashes if a booked trip has no window (mypy flagged `tuple[None,None]`); (3) `cancel_trip` lets a denied/rejected/already-cancelled trip be "cancelled" again; (4) `best_insertion` is O(n³) evaluate calls with no pruning on the drop-off loop (proposal 5.2 s); (5) optional OR-Tools solver = 190 LOC + a repair hack, never chosen by default — complexity without value for an MVP.
**Plan:** add a test posting `name="../../escaped"`; add `slug()` in the proposal module, used by API and CLI; API writes the PDF into a temp dir and returns bytes.
**Review of own diff:** (a) first fix still left every PDF on the server's disk and same-named proposals overwrote each other → now a TemporaryDirectory; (b) CLI had its own ad-hoc slug → reuses `slug()` (one implementation); (c) Content-Disposition header could carry user text → it only ever contains the slug (`[a-z0-9_]`).
**Metrics:** tests 51→53 (all pass); coverage 84→85%; ruff 121; mypy 25; LOC 4544→4551; bench sim 1.96 s, proposal 4.88 s (noise).
**Next:** IVR window crash.

## Iteration 2 — cancellation could erase ADA denials and leak capacity (bug)
**Audit (top 5):** (1) `cancel_trip` accepted denied/rejected/cancelled trips → an ADA denial could be "cancelled" and vanish from the denial KPI; (2) cancelling an en-route trip left it in `unit.onboard` (permanent seat leak) and later vehicle events flipped it to onboard/completed; (3) O(n³) insertion search; (4) OR-Tools complexity; (5) 121 lint / 25 mypy findings. (IVR window "crash" from iteration 1 re-checked: unreachable, every booked trip has a window → type-only issue, deprioritised.)
**Plan:** allow-list `CANCELLABLE` statuses; `Dispatcher.remove_trip` clears onboard + tells the adapter to cancel both stops; simulator skips a cancelled in-flight stop; platform ignores events for cancelled trips.
**Review of own diff:** (a) first version only fixed the status check — the en-route path was still broken → added the simulation test that caught it; (b) `SimulatorAdapter.cancel_stop` returned `Ack(False)` for an in-flight stop, misleading callers → now `Ack(True, "will be skipped")`; (c) defence in depth: platform drops any late event for a cancelled trip, so other adapters (human driver tapping "board" late) can't resurrect it either.
**Metrics:** tests 53→55 pass; coverage 85%; ruff 121; mypy 25; bench unchanged.
**Next:** speed up insertion search (proposal is the slowest path).

## Iteration 3 — prune the insertion search (performance)
**Audit (top 5):** (1) `best_insertion` evaluates every (i, j) pair even after a violation that dooms all later j (proposal 4.8 s, the slowest path); (2) OR-Tools solver complexity; (3) 121 lint findings; (4) 25 mypy errors; (5) KPI / incident / ops code under-tested.
**Plan:** `evaluate_at` returns the index of the first violated node; break the drop-off loop when the violation is at or before the drop-off (prefix shared, drop-off only later); test equality with brute force + an evaluation budget.
**Review of own diff:** (a) one `return None` in the evaluator wasn't converted to the tuple form → would crash on a rare path; fixed and added `test_evaluate_at_reports_first_violation` pinning each failure index; (b) the outer prune had an arbitrary `+60` slack — the prefix is unchanged so the exact bound is safe → tightened; (c) new annotation added a lint finding → modern `X | None`.
**Metrics:** tests 55→57 pass; coverage 85%; ruff 121; mypy 25; **sim 2.03→0.57 s (−72%)**, **proposal 4.83→1.51 s (−69%)**, test suite 33→12.7 s. Plans identical (brute-force equality test; acceptance tests unchanged).
**Next:** simplification — remove the optional OR-Tools solver.

## Iteration 4 — remove the optional OR-Tools solver (simplification)
**Audit (top 5):** (1) `ortools_solver.py` (≈190 LOC incl. a route-repair hack for ride-time semantics it doesn't share with our evaluator) was never the default and only won once in benchmarks — pure complexity for an MVP; (2) batch solver selected by a magic string (`"ortools"`) instead of an object; (3) 120 lint; (4) 25 mypy (4 of them in the OR-Tools file); (5) thin tests for KPIs/incidents.
**Plan:** test that any `Solver` object passed to `Platform(batch_solver=...)` is the one used for batch planning; delete `ortools_solver.py`, `make_solver`, `--solver` flag and the `ortools` extra; update docs.
**Decision (no human available):** the OR-Tools test was removed together with the feature it tested (not to make anything pass). The spec's requirement — "wrap behind a Solver interface so it can be swapped" — is now covered by the plug-in test instead. Re-adding OR-Tools later = one class implementing `Solver`.
**Review of own diff:** (a) my regex left half of the deleted test behind (NameError) → removed cleanly; (b) docstrings in `insertion.py`/`dispatcher.py` and README still mentioned OR-Tools → updated; (c) real-time insertion still always uses the built-in heuristic — intentional (it must be fast); documented in the Platform comment.
**Metrics:** tests 57 pass (−1 OR-Tools, +1 plug-in); coverage 85%; ruff 121→120; **mypy 25→21**; **LOC 4571→4426**; bench unchanged (sim 0.74 s, proposal 1.58 s); one fewer optional dependency.
**Next:** mechanical lint cleanup.

## Iteration 5 — lint gate to zero (quality)
**Audit (top 5):** (1) 120 lint findings incl. real smells: `raise HTTPException` inside `except` without `from` (B904), `zip` without `strict` (B905), unused loop var; (2) no committed lint config — the rule set lived only in my head; (3) 21 mypy errors; (4) KPI/incident/ops tests thin; (5) `api.py` is a 400-line closure.
**Plan:** commit `[tool.ruff]` config to `pyproject.toml`; add `tests/test_quality.py` that runs ruff (fails first); auto-fix safe rules, hand-fix the rest, `ruff format` for long lines.
**Decisions:** ignore B008 (FastAPI `Depends()` idiom) and UP042 (StrEnum changes `str(enum)` output — behavioural risk). One-off `ruff format` across the package accepted (mechanical; makes future diffs smaller).
**Review of own diff:** (a) the formatter inflated the line-count metric (4426→4759) while the code didn't grow → switched the size metric to **coverage statement count** (3385→3382), which formatting can't game; (b) `datetime.timezone.utc`→`datetime.UTC` needs Python ≥3.11 — matches `requires-python`; (c) the quality test skips (not fails) when ruff isn't installed so runtime-only installs still pass.
**Metrics:** tests 57→58 pass; coverage 85%; **ruff 120→0**; mypy 21; statements 3385→3382; bench unchanged.
**Next:** mypy to zero (same gate approach).

## Iteration 6 — type-checker gate to zero (quality)
**Audit (top 5):** (1) 21 mypy errors, some masking real fragility (`tuple(cfg.depot)` copies everywhere because the value was already a tuple; lambdas with default-arg capture; KPI on-time maths on `Optional` fields guarded by a `type: ignore`); (2) no committed mypy config; (3) tests for KPIs/incidents/ops seat thin; (4) `api.py` closure size; (5) README/docs drift after removals.
**Plan:** `[tool.mypy]` in pyproject + `test_mypy_clean` (fails first); fix root causes: drop redundant `tuple(...)`, `functools.partial` instead of default-arg lambdas, KPI on-time computed from `(arrival, window)` pairs (removes the `type: ignore`), explicit row types in GTFS-Flex/raw export.
**Review of own diff:** (a) I first used `assert trip.window is not None` in the IVR — asserts disappear under `python -O` → replaced with a typed fallback; (b) a `type: ignore` was *removed* rather than added (KPI) — net fewer suppressions; (c) the new import broke isort order → ruff fixed; gate tests caught it.
**Metrics:** tests 58→59 pass; coverage 85%; ruff 0; **mypy 21→0**; statements 3382→3386; bench unchanged (sim 0.67 s, proposal 1.58 s).
**Next:** raise coverage on the least-tested business logic (incidents, ops seat, KPIs).

## Iteration 7 — incident workflow + ops queue tests; undeliverable notices surfaced (coverage + bug)
**Audit (top 5):** (1) `ops/incidents.py` at 39% coverage — the insurer/police notification rules had no test; (2) vehicle-fault rescue path in the dispatcher untested (lines 290–333); (3) CLI 0% coverage; (4) GTFS import untested; (5) GTFS-RT trip updates untested.
**Plan:** test notification routing by severity/injury, close-out, tenant-scoped API, queue ordering and seat-simulation priority.
**Honest note:** the routing/queue tests passed on first run (no bug there) — this part is coverage only. Review of the code under test then found a real gap, handled test-first: a missing contact (e.g. no police/fire number) was "sent" to a placeholder string and counted as notified.
**Fix:** notifications carry `delivered: bool`; a missing contact is recorded as undelivered (not sent) and the API raises an `incident_notice_undelivered` ops exception (severity high).
**Review of own diff:** (a) close-out report still listed undelivered parties under "Notified" → split into "Notified" / "Not delivered"; (b) moved a function-local `import pytest` to module top; (c) gave the new exception type a handling-time estimate so seat-load maths stays meaningful.
**Metrics:** tests 59→64 pass; **coverage 85→86%** (incidents 39→~100%); ruff 0; mypy 0; bench unchanged.
**Next:** vehicle-fault rescue path test (highest-risk untested logic).
