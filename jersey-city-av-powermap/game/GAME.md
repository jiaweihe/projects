# Jersey City AV Game: a multi-dimensional game

_As of 2026-11-09. Horizon: 3-year pilot window (2027-2029). Open `index.html` for the interactive version with sliders._

## 2027 outlook, whatever happens to S1677

_Will autonomous vehicles operate on Jersey City streets in 2027, whatever happens to S1677?_

NJ has no AV statute, so nothing authorizes or bans driverless operation. S1677/A3968 sits in Senate Budget & Appropriations, and its 2024-25 version (S4702) died. Operators can choose to launch; the State can respond after the fact.

**The game:** Waymo and Tesla each choose to wait, test with safety drivers, or launch driverless (simultaneous logit equilibrium; no pure equilibrium exists in the legal gap). Then the City sets curb policy, then the State (Gov. + MVC) tolerates, adds conditions, or halts. It is played under two legal regimes, today's gap and S1677 enacted, blended by P(S1677 law before 2027) = 10-30%.

| Calibrated model, 2,000 runs | 2026 (check vs today) | **2027** |
|---|:-:|:-:|
| Any driverless AV carrying riders in JC | 2% | **69%** |
| Waymo driverless | 1% | 46% |
| Tesla driverless | 1% | 48% |
| Any AV on JC streets, incl. testing | 93% | 98% |
| State deliberately halts a launch | 0% | 0% |
| Expected chance a crash forces a halt | 0% | 13% |

2027 operator strategies at midpoints. Legal gap: Waymo wait 17%, test 40%, driverless 44%; Tesla wait 5%, test 20%, driverless 75%. Under S1677: Waymo wait 19%, test 47%, driverless 34%; Tesla wait 19%, test 81%.

Most likely 2027 paths: gap → driverless → driverless → managed → tolerate **23%**; gap → test → driverless → managed → conditions **12%**; gap → driverless → test → managed → tolerate **11%**; gap → test → test → open → tolerate **11%**.

**What it says:**
1. **The 2026 check holds.** Under today's gap the model has nobody running driverless in 2026, which matches reality: Waymo is mapping JC with drivers. The permission-first cost is calibrated to that fact, and Waymo itself says it won't launch until NJ changes its rules.
2. **2027 turns on operators, not Trenton.** In the gap both operators mix between testing and launching. **Tesla is the likelier first mover** because it bears a lower cost for launching without permission. S1677 would keep Tesla out entirely and slow Waymo, consistent with Waymo's 'delays us to 2028'.
3. **The State's tool is conditions, not a ban.** Within sourced ranges the State never prefers a deliberate halt: the MVC's safety weight values Waymo's crash record, so it adds conditions instead. The real halt risk is a crash forcing one (the Cruise 2023 pattern).
4. **Curb management is the City's lever** either way: managed curb in most paths. Waymo-Via integration only happens if Waymo launches and the curb isn't restricted.

Sources: <https://newjerseymonitor.com/2026/05/13/driverless-cars-nj-senate/> · <https://legiscan.com/NJ/bill/S1677/2026> · <https://law.justia.com/codes/new-jersey/title-39/section-39-5h-2/> · <https://njballot.com/post/nj-robotaxi-bill-s1677> · <https://www.thecityreporter.nyc/2026/04/06/waymo-driverless-cars-testing-roads-autonomous-vehicle/> · <https://www.engadget.com/2016/12/22/uber-self-driving-tests-california-to-arizona/> · <https://www.axios.com/2023/10/24/cruise-permit-suspended-driverless-cars> · <https://nj1015.com/autonomous-vehicles-waymo-pilot-program/> · <https://www.robotaxiatlas.com/operators/waymo/>

---

# If Trenton legislates first: the S1677 game

## The game

1. **Legislature** (Zwicker, S1677 sponsor) proposes: stall / S1677 as written / industry-amended / moratorium
2. **Governor** (Sherrill) signs or vetoes; a veto means stall
3. **City** (Mayor Solomon + Dept. of Infrastructure) sets curb policy: open / managed / restrict
4. **Waymo, Tesla, Via** choose at the same time whether to enter or integrate (pure Nash equilibrium)

Solved by backward induction. Each of 14 actors scores outcomes on **6 dimensions**: safety, risk, congestion, jobs, budget, access, innovation, plus revenue for the firms. The Legislature and Governor weigh their own priorities 50/50 against a power-weighted coalition of everyone else, using power scores from the power map.

## Units

- **safety**: 1 pt = 5% fewer serious-injury crashes in JC
- **risk**: 1 pt = 50% chance of a forced halt
- **jobs**: 1 pt = 10% of JC rideshare trips kept by human drivers
- **budget**: 1 pt = $2M/yr (JC paid ~$7.7M/yr for Via)
- **access**: 1 pt = restoring the Via evening + Saturday service cut on July 1, 2026
- **innovation**: 1 pt = a full commercial robotaxi launch in the NJ market
- **congestion**: 1 pt = 2% of JC vehicle-miles (negative = more traffic)

## Result at sourced midpoints

**Equilibrium: Industry-amended → signed → Managed curb → waymo + tesla + via** (chance of a forced halt 40%)

| Actor | power | Stall (no AV law) | S1677 as written | Industry-amended | Moratorium | favorite |
|---|:-:|:-:|:-:|:-:|:-:|---|
| Waymo | 4 | +0.00 | +0.15 | +0.71 | +0.00 | Industry-amended |
| Tesla | 2 | +0.00 | +0.05 | +0.84 | +0.00 | Industry-amended |
| Via | 3 | +0.00 | +0.43 | +0.86 | +0.00 | Industry-amended |
| JC Infrastructure | 3 | +0.00 | +0.44 | +0.76 | +0.00 | Industry-amended |
| Bike JC | 2 | +0.00 | +0.44 | +0.72 | +0.00 | Industry-amended |
| Safe Streets JC | 2 | +0.00 | +0.44 | +0.70 | +0.00 | Industry-amended |
| NJ Transit | 4 | +0.00 | +0.43 | +0.91 | +0.00 | Industry-amended |
| NJ MVC | 5 | +0.00 | +0.45 | +0.69 | +0.00 | Industry-amended |
| NJDOT | 3 | +0.00 | +0.44 | +0.92 | +0.00 | Industry-amended |
| Port Authority | 3 | +0.00 | +0.35 | +1.00 | +0.00 | Industry-amended |
| Gig drivers | 1 | +0.00 | −0.34 | −1.00 | +0.00 | Stall (no AV law) |
| Mayor Solomon | 3 | +0.00 | +0.43 | +0.77 | +0.00 | Industry-amended |
| Legislature (Zwicker) | 4 | +0.00 | +0.37 | +0.53 | +0.00 | Industry-amended |
| Gov. Sherrill | 5 | +0.00 | +0.35 | +0.64 | +0.00 | Industry-amended |
| NYC (Mamdani/DOT) | 2 | +0.00 | −0.11 | −0.62 | +0.00 | Stall (no AV law) |
| NY State (Hochul) | 1 | +0.00 | +0.16 | +0.52 | +0.00 | Industry-amended |
| MTA | 1 | +0.00 | +0.43 | +0.69 | +0.00 | Industry-amended |
| NYC driver unions | 2 | +0.00 | −0.34 | −1.00 | +0.00 | Stall (no AV law) |
| ATU (transit labor) | 3 | +0.00 | −0.05 | −0.43 | +0.00 | Stall (no AV law) |
| Open Plans | 1 | +0.00 | +0.43 | +0.79 | +0.00 | Industry-amended |
| RPA | 2 | +0.00 | +0.43 | +0.93 | +0.00 | Industry-amended |
| AAA clubs | 2 | +0.00 | +0.29 | −0.31 | +0.00 | S1677 as written |
| Chamber of Progress | 2 | +0.00 | +0.32 | +1.00 | +0.00 | Industry-amended |
| Blind & disability advocates | 2 | +0.00 | +0.44 | +0.84 | +0.00 | Industry-amended |
| Uber | 3 | +0.00 | +0.35 | +1.00 | +0.00 | Industry-amended |
| Teamsters | 3 | +0.00 | −0.25 | −0.92 | +0.00 | Stall (no AV law) |
| Auto Innovation (AAI) | 2 | +0.00 | +0.32 | +1.00 | +0.00 | Industry-amended |

Utilities are normalized per actor: −1 is the worst reachable outcome, +1 the best.

| Dimension | S1677 | Amended |
|---|:-:|:-:|
| safety | +0.25 | +0.56 |
| risk | −0.03 | −0.79 |
| congestion | −0.05 | −0.23 |
| jobs | −0.22 | −0.65 |
| budget | +0.45 | +0.87 |
| access | +0.35 | +0.83 |
| innovation | +0.30 | +1.01 |

## Robustness (2,000 runs: effects redrawn within their ranges, weights scaled ±50%)

| Path | Default weights | Legislature risk weight 0.30 |
|---|:-:|:-:|
| amended → signed → managed → waymo+tesla+via | 69.2% | 41.5% |
| s1677 → signed → managed → waymo+via | 29.4% | 54.1% |
| stall → signed → open → no entry | 0.8% | 2.3% |
| s1677 → signed → open → waymo+via | 0.7% | 2.1% |

## The New York effect

The same game run with and without the 10 NY-region and advocacy actors in the coalition:

| | NJ actors only | + NY region & advocacy |
|---|:-:|:-:|
| Legislature's margin for amended over S1677 | +0.23 | +0.16 |
| Robustness runs won by amended | 78% | 69% |
| Backlash-risk weight at which S1677 wins | 0.30 | 0.26 |

NY labor (IDG, ATU), NYC's worker-first DOT, and congestion-focused advocates (Open Plans, AAA) pull the Legislature toward S1677. The tech industry and blind/disability advocates pull the other way, toward more driverless miles. On balance New York makes S1677 easier to justify: less of a risk premium is needed to pick it.

## Calibration with Beli-style answers

Weights are tuned with Boolean answers ("for this actor, does A matter more than B?"), fitted with Bradley–Terry. The original weights count as a prior worth α=4 answers. The 5 answers in `evidence.json` are revealed preferences with sources.

| | Raw weights | Calibrated |
|---|:-:|:-:|
| Observed facts reproduced | 8/8 | 10/8 |
| Equilibrium | amended → signed → managed → waymo+tesla+via | s1677 → signed → managed → waymo+via |
| Robustness runs won by S1677 | 30% | 65% |

Facts: ✓ NJ Senate committee advanced S1677 (5-0), not the industry-amended bill; ✓ Waymo is preparing to operate under S1677-style rules (mapping JC, Newark tests); ✓ Waymo wants the safety-driver phase removed (prefers amended); ✓ Gig-driver petitioners want AVs stopped in NJ; ✓ Chamber of Progress supports S1677 only with loosening amendments; ✓ Blind/disability advocates and SAVE-US testified for S1677; ✓ NY Gov. Hochul withdrew her robotaxi-service plan (prefers stall to a loose law); ✓ NYC driver unions fought robotaxis and claimed victory when the plan died; ✓ Teamsters fight robotaxi legalization and push human-operator mandates (DC, MA, TX); ✓ ATU opposed NJDOT's Trenton AV transit project and wants AVs barred from transit.

**How fragile is it?** The prior-strength sweep gives α=1: 10/8 · α=2: 10/8 · α=4: 10/8 · α=8: 9/8 · α=16: 8/8. Dropping one answer at a time:

| Answer dropped | Fit |
|---|:-:|
| Legislature (Zwicker): risk > innovation | 9/8 (misses committee_s1677) |
| Legislature (Zwicker): safety > innovation | 10/8  |
| Mayor Solomon: budget > access | 10/8  |
| NY State (Hochul): jobs > innovation | 9/8 (misses hochul_withdrew) |
| NYC (Mamdani/DOT): jobs > safety | 10/8  |
| Uber: jobs > innovation | 10/8  |

Each missed fact is fixed by one targeted answer, so the calibration fits the record rather than predicting it. Treat it as a consistency check. New, out-of-sample observations (an S1677 floor vote, Gov. Sherrill's signature) would be the real test.

## Probabilistic play (logit quantal response)

Movers don't always pick their best option. The Legislature, Governor and City choose by logit, P ∝ exp(λ·U). λ is rationality: 0 is random, ∞ is the strict best choice. Operators keep their pure Nash equilibrium, because firms optimize harder than political bodies. Grading becomes the probability the model gave to what actually happened.

| P(committee picks S1677) | λ=2 | λ=4 | λ=8 | λ=16 |
|---|:-:|:-:|:-:|:-:|
| Raw weights | 0.28 (log-loss 1.26) | 0.27 (log-loss 1.31) | 0.18 (log-loss 1.70) | 0.06 (log-loss 2.80) |
| Calibrated (Beli answers) | 0.30 (log-loss 1.22) | 0.36 (log-loss 1.02) | 0.53 (log-loss 0.63) | 0.79 (log-loss 0.23) |

Most likely paths, calibrated, λ=8: s1677 → signed → managed → waymo+via **35%**; amended → signed → managed → waymo+tesla+via **22%**; s1677 → signed → open → waymo+via **13%**; stall → signed → open → no entry **4%**.

λ cannot be fitted from one vote; λ=8 is the default, and the sweep shows the calibrated model wins at every λ.

## What the model says

1. **The committee's choice reveals a risk premium.** Every actor except gig drivers scores the amended bill higher, because the benefits scale with how long cars run driverless. Yet the Senate committee advanced S1677 with a 5-0 vote. The model reproduces that only if the Legislature puts at least **0.26** weight on backlash risk, the chance a serious crash forces a Cruise-style halt. That is the real price of the human-driver phase.
2. **Tesla's swing variable is evidence, not lobbying.** Take the Legislature's revealed risk weight of 0.30. Once Tesla's halt chance drops below **0.39** per driverless window, the Legislature itself prefers letting Tesla in, because then the amended bill wins. Owner lobbying moves nothing in this model. Verified crash data published through NHTSA would.
3. **The Governor is not the bottleneck.** She keeps signing the amended bill unless her weight on driver jobs passes **0.60**, far above any stated priority.
4. **The city holds a quiet veto.** With a restricted curb under S1677, Waymo **stays out**: the expected revenue no longer covers the entry cost. The Mayor's best response is a **managed curb** in every branch. The city takes curb fees plus Via integration savings of about $1-3M/yr against a ~$90M deficit, and trades access for safety rules.
5. **Via is the city's lever on the budget.** Via only integrates when Waymo is in and the curb is not restricted. That makes Via the bridge between the Mayor's budget priority and Waymo's entry. The Chandler, AZ model is the playbook.

## Limits

- Effect sizes and weights are assumptions anchored to sources (see `model.json` → `basis`/`src` for each block). They are not measurements.
- Halt hazards are assumptions; there is no public per-mile crash rate for Tesla Robotaxi.
- One-shot game. Repeated play (pilot renewals, the 2029 sunset) and side payments (labor transition funds) are not modeled.
