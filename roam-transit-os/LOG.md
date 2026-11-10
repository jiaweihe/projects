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
