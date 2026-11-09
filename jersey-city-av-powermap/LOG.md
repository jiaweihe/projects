# Autonomous session log

**GOAL:** make the mechanism, the grading and the weights more sophisticated, and use Beli-style Boolean (A vs B) comparisons for quick fine-tuning.
**Start:** Mon Nov 9 18:08:49 UTC 2026 · branch `session/2026-11-09`, cut from `claude/jersey-city-autonomous-stakeholders-v0kadz`; main is untouched.
**Verify command:** `./check.sh` runs the pytest and node tests with coverage, eslint, pyflakes and `tsc --checkJs`. The tools sit in the scratchpad, not in the repo. Decision: lint and type-check through tools kept outside the repo, so no project dependencies are added.

## Baseline

| Metric | Value |
|---|---|
| Tests | 23/23 pass (12 pytest + 11 node; 45 live-link tests skipped offline) |
| Coverage (node, game/*.js) | lines 100%, branches 93.75% |
| Lint | eslint 1 error (unused `PROFILES` in solver.test.js); pyflakes 0 |
| Type errors (tsc --checkJs solver.js) | 0 |
| **Key metric: observed-behavior fit** | **6/8 real-world facts reproduced** |
| Beli comparisons supported | 0 |

Observed facts used for the fit score:
1. The Senate committee advanced S1677, not the amended bill. **FAIL**
2. Waymo enters under S1677 (it is mapping JC now). PASS
3. Waymo prefers the amended bill to S1677 (Walsh testimony). PASS
4. Gig drivers prefer no AV law. PASS
5. Chamber of Progress prefers the amended bill. PASS
6. Disability advocates prefer S1677 to stall. PASS
7. NY State (Hochul) prefers stall to an amended-style robotaxi law; she withdrew her plan. **FAIL**
8. NYC driver unions prefer stall. PASS

## Iteration 1: codify grading (observed-behavior fit + letter grades)
**Audit, top 3:** (1) the fit score is ad-hoc and untested; (2) weights are hand-typed, with no comparison-based tuning; (3) movers pick a single best option, so there are no choice probabilities.
**Plan:** add `game/calibrate.js`, holding the 8 sourced observed facts, `fit(model)` and `letter(u)` grades.
Lock the 6/8 baseline in a test, so later iterations can only move it up.
Fix the eslint unused-variable error.
**Built:** `game/calibrate.js`: 8 sourced facts, `fit()`, and `letter()` grades A to F. Test-first: 4 tests failed before the module existed, then passed.
**Review fixes:** (1) `tsc` now also checks calibrate.js; (2) the "Waymo enters under S1677" fact now reads the signed-S1677 subgame, so a veto on the path can't hide it.
**Metrics:** tests 23→27, all passing · eslint 1→**0** · tsc 0→0 · fit 6/8, now graded by code instead of an ad-hoc script · branch coverage 93.75→93.26%. The small drop comes from the browser-only export path; it is still uncovered.
**Next:** a Beli pairwise engine to learn weights from A-vs-B answers.

## Iteration 2: Beli pairwise engine (Boolean A-vs-B → weights)
**Audit, top 3:** (1) no way to tune weights by comparison, which is the core of the GOAL; (2) mover decisions are argmax only; (3) weights are not tied to evidence.
**Plan:** add `game/prefs.js`. It fits weights with Bradley–Terry MAP, treating the current weights as a prior worth α pseudo-comparisons.
Beli-style tools: `nextPair()` asks about the most uncertain, least-asked pair; `insertRank()` places an item with binary insertion in O(log n) questions.
Metric: weight-recovery MAE from simulated answers, prior only vs after 10 and 30 answers.
**Built:** `game/prefs.js`. `fitWeights` does Bradley–Terry MAP via MM, with the prior worth α=4 answers. Also `nextPair` (Beli: the most uncertain, least-asked pair), `insertRank` (binary insertion, ≤ ⌈log₂(n+1)⌉ questions), `applyComparisons` and `simulate`. Test-first: 7 tests failed, then passed.
**Review fixes:** (1) `simulate` over-sampled the last dimension, fixed with uniform sampling and a test; (2) self-comparisons are dropped and invalid `win` values throw; (3) α=0 is guarded against NaN; (4) a tsc type error was fixed with a JSDoc annotation.
**Metrics:** tests 27→37, all passing · branch coverage 93.26→**93.61%** · lint 0 · tsc 0 · **Beli comparisons supported: 0 → yes**. **Weight-recovery MAE** (mean of 50 simulated respondents, 3 dimensions, prior off by 0.2): prior only 0.200 → **0.102 after 10 answers**, 0.072 after 30. Fit is unchanged at 6/8, because no answers have been applied yet.
**Next:** feed sourced evidence in as Boolean comparisons for the actors whose behavior the model misses (Legislature, Hochul), and check the fit.
