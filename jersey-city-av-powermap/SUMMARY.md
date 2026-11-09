# Session summary (2026-11-09, 5 iterations)
| Metric | Baseline | Final |
|---|---|---|
| Real outcomes reproduced | 6/8 | **10/10** (2 labor facts added later) |
| P(committee picks S1677), λ=8 | n/a (argmax) | 0.18 raw → **0.53** |
| Tests passing | 23 | **48** (+1 browser test) |
| Branch coverage / lint / type errors | 93.8% / 1 / 0 | **94.3% / 0 / 0** |

**Changed:** grading against 8 sourced facts; Beli-style A-vs-B weight learning (Bradley–Terry); 5 sourced answers calibrate weights; logit choice probabilities; on-page quick-tune with undo.
**Open:** calibration fits the record (each fixed fact rests on one answer); λ is set, not fitted; Python has no coverage tool.
**Next (human):** test against the S1677 floor vote and Sherrill's signature; review the 5 answers in `game/evidence.json`; merge `session/2026-11-09`.
