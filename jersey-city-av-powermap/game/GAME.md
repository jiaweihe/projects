# Jersey City AV Game: a multi-dimensional game

_As of 2026-11-09. Horizon: 3-year pilot window (2027-2029). Open `index.html` for the interactive version with sliders._

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
| Legislature (Zwicker) | 4 | +0.00 | +0.38 | +0.54 | +0.00 | Industry-amended |
| Gov. Sherrill | 5 | +0.00 | +0.37 | +0.66 | +0.00 | Industry-amended |
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
| amended → signed → managed → waymo+tesla+via | 71.1% | 45.1% |
| s1677 → signed → managed → waymo+via | 28.1% | 51.8% |
| stall → signed → open → no entry | 0.4% | 1.2% |
| s1677 → signed → open → waymo+via | 0.4% | 1.9% |

## The New York effect

The same game run with and without the 10 NY-region and advocacy actors in the coalition:

| | NJ actors only | + NY region & advocacy |
|---|:-:|:-:|
| Legislature's margin for amended over S1677 | +0.23 | +0.16 |
| Robustness runs won by amended | 78% | 71% |
| Backlash-risk weight at which S1677 wins | 0.30 | 0.26 |

NY labor (IDG, ATU), NYC's worker-first DOT, and congestion-focused advocates (Open Plans, AAA) pull the Legislature toward S1677. The tech industry and blind/disability advocates pull the other way, toward more driverless miles. On balance New York makes S1677 easier to justify: less of a risk premium is needed to pick it.

## What the model says

1. **The committee's choice reveals a risk premium.** Every actor except gig drivers scores the amended bill higher, because the benefits scale with how long cars run driverless. Yet the Senate committee advanced S1677 with a 5-0 vote. The model reproduces that only if the Legislature puts at least **0.26** weight on backlash risk, the chance a serious crash forces a Cruise-style halt. That is the real price of the human-driver phase.
2. **Tesla's swing variable is evidence, not lobbying.** Take the Legislature's revealed risk weight of 0.30. Once Tesla's halt chance drops below **0.40** per driverless window, the Legislature itself prefers letting Tesla in, because then the amended bill wins. Owner lobbying moves nothing in this model. Verified crash data published through NHTSA would.
3. **The Governor is not the bottleneck.** She keeps signing the amended bill unless her weight on driver jobs passes **0.61**, far above any stated priority.
4. **The city holds a quiet veto.** With a restricted curb under S1677, Waymo **stays out**: the expected revenue no longer covers the entry cost. The Mayor's best response is a **managed curb** in every branch. The city takes curb fees plus Via integration savings of about $1-3M/yr against a ~$90M deficit, and trades access for safety rules.
5. **Via is the city's lever on the budget.** Via only integrates when Waymo is in and the curb is not restricted. That makes Via the bridge between the Mayor's budget priority and Waymo's entry. The Chandler, AZ model is the playbook.

## Limits

- Effect sizes and weights are assumptions anchored to sources (see `model.json` → `basis`/`src` for each block). They are not measurements.
- Halt hazards are assumptions; there is no public per-mile crash rate for Tesla Robotaxi.
- One-shot game. Repeated play (pilot renewals, the 2029 sunset) and side payments (labor transition funds) are not modeled.
