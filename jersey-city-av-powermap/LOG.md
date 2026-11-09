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

## Iteration 3: sourced evidence as Boolean answers → calibrated weights
**Audit, top 3:** (1) the model misses 2 of 8 observed facts (committee vote, Hochul); (2) GAME.md and the page show uncalibrated weights; (3) movers' choices are argmax only.
**Plan:** add `game/evidence.json` with 5 revealed-preference answers, each with a source and a reason, plus `prefs.withEvidence(model)`.
Test-first: every answer is sourced and valid, and the calibrated fit beats the baseline.
Make GAME.md report the calibrated model alongside the raw one.
**Built:** `evidence.json` holds 5 sourced revealed-preference answers (Zwicker ×2, Solomon, Hochul, Mamdani). `prefs.withEvidence()` applies them. GAME.md gains a calibration section: raw vs calibrated, an α sweep, and a leave-one-out table. Test-first: the calibration test failed until `withEvidence` existed.
**Review fixes:** (1) Overfitting risk: leave-one-out shows each fixed fact depends on one targeted answer. This is now stated plainly in GAME.md as fitting the record, not predicting it. (2) α=4 was arbitrary: the sweep shows 8/8 for α≤4, 7/8 at 8, 6/8 at 16, and a test now guards fit ≥7 for α≤8.
**Metrics:** **fit 6/8 → 8/8** · S1677 robustness share 29% → 63% · tests 37→40, all passing · branch coverage 93.61→93.80% · lint 0 · tsc 0.
**Next:** make the mechanism probabilistic (logit quantal response), so the model gives choice probabilities and can be scored by log-likelihood, not just pass/fail.

## Iteration 4: probabilistic mechanism (logit quantal response) + log-loss grading
**Audit, top 3:** (1) movers use hard argmax, so the model can't say how likely an outcome is, and fit (8/8) is now saturated as a metric; (2) the page doesn't expose Beli tuning yet; (3) GAME.md headline results still use raw weights.
**Plan:** add `solveQR(model, {lambda})`, softmax choices for Legislature, Governor and City (operators keep their pure Nash equilibrium). It returns law and path probabilities.
New grading metric: P(observed committee choice = S1677) and its log-loss, raw vs calibrated.
Test-first: probabilities sum to 1; λ=0 is uniform; large λ recovers argmax; more risk weight raises P(S1677).
**Built:** `solveQR()` in solver.js: a logit quantal-response equilibrium over Legislature, Governor and City, returning law, sign and path probabilities. GAME.md gains a probabilistic-play section. Test-first: 5 tests failed, then passed.
**Review fixes:** (1) λ is unfittable from one vote, so a λ-sweep test now guards that calibration beats raw at λ ∈ {2,4,8,16}; (2) the mixed design (noisy politicians, exact operators) is now explained in GAME.md; (3) added a Governor sign-probability bounds test.
**Metrics:** **P(observed committee choice) at λ=8: 0.18 → 0.53; log-loss 1.73 → 0.63** · tests 40→47, all passing · branch coverage 93.80→**94.30%** · lint 0 · tsc 0.
**Next:** put Beli quick-tuning on the page: A-vs-B buttons per actor that live-update the weights and equilibrium.

## Iteration 5: Beli quick-tune on the page + calibrated defaults
**Audit, top 3:** (1) Beli tuning exists only as a library, not in the UI the user tunes with; (2) the page still shows raw weights and no grade or fit readout; (3) the page has no automated browser test.
**Plan:** inline prefs, calibrate and evidence into the page. Add a Quick-tune panel (actor, A / B / about equal, undo) driven by `nextPair` and `fitWeights`, plus a readout of fit x/8 and P(S1677).
Sliders override only once touched, so they don't wipe out tuned weights.
Test-first: a Playwright e2e test (Playwright is preinstalled in the environment, not added to the repo) checks that answering changes the weights and the equilibrium readout.
**Built:** the page now inlines prefs, calibrate and evidence, and opens on the calibrated model. A Quick-tune panel picks an actor, asks the most informative "which matters more?" pair (Beli `nextPair`), offers A / B / about-equal and undo, and shows live weight bars. A readout shows fit x/8 and P(S1677) at λ=8, and heatmap tooltips carry letter grades. Untouched sliders track the tuned weights. Test-first: `page.e2e.js` failed (no panel), then passed. It is wired into `check.sh`.
**Review fixes:** (1) the hard-coded "8 of 8" label is now computed from the evidence; (2) A/B buttons got `aria-describedby` for screen readers; (3) the Governor tipping card showed a vacuous "≥ 0.00" when amended wasn't the outcome. It now says n/a, and an e2e assertion guards it. The assertion was added together with the fix, not before it.
**Metrics:** e2e browser tests 0→**1** (with 6 assertions, including 12 Beli answers flipping the equilibrium) · page answers supported 0→**unlimited, with undo** · tests 47→48 · branch coverage 94.30% (unchanged) · lint 0 · tsc 0 · no console errors and no overflow at 1280px light or 400px dark.
**Next:** an out-of-sample test (the S1677 floor vote, Sherrill's signature); save tuned answers per viewer; fit λ once more votes exist.
