// node build.js  -> index.html (interactive page) + GAME.md (static summary)
const fs = require("fs"), path = require("path");
const g = require("./solver.js"), m = require("./model.json");
const prefs = require("./prefs.js"), cal = require("./calibrate.js"), ev = require("./evidence.json");
const here = f => path.join(__dirname, f);

const page = fs.readFileSync(here("page.template.html"), "utf8")
  .replace("/*SOLVER*/", () => fs.readFileSync(here("solver.js"), "utf8"))
  .replace("/*PREFS*/", () => fs.readFileSync(here("prefs.js"), "utf8"))
  .replace("/*CALIBRATE*/", () => fs.readFileSync(here("calibrate.js"), "utf8"))
  .replace("/*MODEL*/", () => JSON.stringify(m))
  .replace("/*EVIDENCE*/", () => JSON.stringify(ev));
fs.writeFileSync(here("index.html"), page);

const s = g.solve(m), B = s.branches, laws = Object.keys(B), ids = Object.keys(m.players);
const f = x => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(2);
const ops = a => ["waymo", "tesla", "via"].filter(k => a[k]).join(" + ") || "no entry";
const th = (id, d, t) => g.threshold(x => g.setWeight(m, id, d, x), t, 0, 0.95);
const tRisk = th("zwicker", "risk", e => e.law === "s1677");
const tJobs = th("gov_sherrill", "jobs", e => !(e.proposed === "amended" && e.sign));
const m30 = g.setWeight(m, "zwicker", "risk", 0.3);
const tTes = g.threshold(x => { const c = JSON.parse(JSON.stringify(m30)); c.operators.tesla.hazard = [1 - x, 1 - x]; return c; }, e => e.law === "amended", 0, 1);
const rob = g.robustness(m, 2000, 7, 0.5);
const r3 = g.robustness(g.setWeight(m, "zwicker", "risk", 0.3), 2000, 7, 0.5);
const R = s.resolved;
// New York effect: same game with the NY-region / advocacy actors removed from the coalition.
const mNJ = JSON.parse(JSON.stringify(m));
for (const k of Object.keys(mNJ.players)) if (mNJ.players[k].region) delete mNJ.players[k];
const njOnly = { rob: g.robustness(mNJ, 2000, 7, 0.5), tRisk: g.threshold(x => g.setWeight(mNJ, "zwicker", "risk", x), e => e.law === "s1677", 0, 0.95),
  gap: (z => z.amended.u.zwicker - z.s1677.u.zwicker)(g.solve(mNJ).branches) };
const share = (rows, law) => rows.filter(r => r.path.startsWith(law + "|")).reduce((a, r) => a + r.share, 0);
const restrict = g.operatorsNE(R, "s1677", "restrict").a;

const md = [
`# ${m.title}: a multi-dimensional game`, "",
`_As of ${m.as_of}. Horizon: ${m.horizon}. Open \`index.html\` for the interactive version with sliders._`, "",
"## The game", "",
"1. **Legislature** (Zwicker, S1677 sponsor) proposes: stall / S1677 as written / industry-amended / moratorium",
"2. **Governor** (Sherrill) signs or vetoes; a veto means stall",
"3. **City** (Mayor Solomon + Dept. of Infrastructure) sets curb policy: open / managed / restrict",
"4. **Waymo, Tesla, Via** choose at the same time whether to enter or integrate (pure Nash equilibrium)", "",
"Solved by backward induction. Each of 14 actors scores outcomes on **6 dimensions**: " + g.DIMS.join(", ") +
", plus revenue for the firms. The Legislature and Governor weigh their own priorities 50/50 against a power-weighted coalition of everyone else, using power scores from the power map.", "",
"## Units", "", ...Object.entries(m.units).map(([k, v]) => `- **${k}**: ${v}`), "",
"## Result at sourced midpoints", "",
`**Equilibrium: ${m.laws[s.eq.proposed].label} → ${s.eq.sign ? "signed" : "vetoed"} → ${m.city[s.eq.city].label} → ${ops(s.eq.a)}** (chance of a forced halt ${(s.eq.o.pHalt * 100).toFixed(0)}%)`, "",
"| Actor | power | " + laws.map(l => m.laws[l].label).join(" | ") + " | favorite |",
"|---|:-:|" + laws.map(() => ":-:").join("|") + "|---|",
...ids.map(id => { const v = laws.map(l => B[l].u[id]); const b = laws[v.indexOf(Math.max(...v))];
  return `| ${m.players[id].name} | ${m.players[id].power} | ${v.map(f).join(" | ")} | ${m.laws[b].label} |`; }), "",
"Utilities are normalized per actor: −1 is the worst reachable outcome, +1 the best.", "",
"| Dimension | S1677 | Amended |", "|---|:-:|:-:|",
...g.DIMS.map(d => `| ${d} | ${f(B.s1677.o.v[d])} | ${f(B.amended.o.v[d])} |`), "",
"## Robustness (2,000 runs: effects redrawn within their ranges, weights scaled ±50%)", "",
"| Path | Default weights | Legislature risk weight 0.30 |", "|---|:-:|:-:|",
...[...new Set([...rob, ...r3].map(r => r.path))].map(p => `| ${p.replace(/\|/g, " → ")} | ${((rob.find(r => r.path === p) || { share: 0 }).share * 100).toFixed(1)}% | ${((r3.find(r => r.path === p) || { share: 0 }).share * 100).toFixed(1)}% |`), "",
"## The New York effect", "",
"The same game run with and without the 10 NY-region and advocacy actors in the coalition:", "",
"| | NJ actors only | + NY region & advocacy |", "|---|:-:|:-:|",
`| Legislature's margin for amended over S1677 | ${f(njOnly.gap)} | ${f(B.amended.u.zwicker - B.s1677.u.zwicker)} |`,
`| Robustness runs won by amended | ${(share(njOnly.rob, "amended") * 100).toFixed(0)}% | ${(share(rob, "amended") * 100).toFixed(0)}% |`,
`| Backlash-risk weight at which S1677 wins | ${njOnly.tRisk.toFixed(2)} | ${tRisk.toFixed(2)} |`, "",
"NY labor (IDG, ATU), NYC's worker-first DOT, and congestion-focused advocates (Open Plans, AAA) pull the Legislature toward S1677. The tech industry and blind/disability advocates pull the other way, toward more driverless miles. On balance New York makes S1677 easier to justify: less of a risk premium is needed to pick it.", "",
...(() => {
  const tuned = prefs.withEvidence(m, ev), fr = cal.fit(m), ft = cal.fit(tuned), st = g.solve(tuned);
  const amShare = rows => (share(rows, "s1677") * 100).toFixed(0) + "%";
  const alphas = [1, 2, 4, 8, 16].map(a => `α=${a}: ${cal.fit(prefs.applyComparisons(m, ev.comparisons, a)).passed}/8`).join(" · ");
  const loo = Object.entries(ev.comparisons).flatMap(([id, cs]) => cs.map((x, i) => {
    const E = JSON.parse(JSON.stringify(ev)); E.comparisons[id].splice(i, 1);
    const r = cal.fit(prefs.withEvidence(m, E));
    return `| ${m.players[id].name}: ${x.a} > ${x.b} | ${r.passed}/8 ${r.results.filter(z => !z.pass).map(z => "(misses " + z.id + ")").join(" ")} |`; }));
  return ["## Calibration with Beli-style answers", "",
    "Weights are tuned with Boolean answers (\"for this actor, does A matter more than B?\"), fitted with Bradley–Terry. The original weights count as a prior worth α=4 answers. The 5 answers in `evidence.json` are revealed preferences with sources.", "",
    "| | Raw weights | Calibrated |", "|---|:-:|:-:|",
    `| Observed facts reproduced | ${fr.passed}/8 | ${ft.passed}/8 |`,
    `| Equilibrium | ${g.pathKey(s.eq).replace(/\|/g, " → ")} | ${g.pathKey(st.eq).replace(/\|/g, " → ")} |`,
    `| Robustness runs won by S1677 | ${amShare(rob)} | ${amShare(g.robustness(tuned, 2000, 7, 0.5))} |`, "",
    "Facts: " + ft.results.map(r => (r.pass ? "✓ " : "✗ ") + r.claim).join("; ") + ".", "",
    "**How fragile is it?** The prior-strength sweep gives " + alphas + ". Dropping one answer at a time:", "",
    "| Answer dropped | Fit |", "|---|:-:|", ...loo, "",
    "Each missed fact is fixed by one targeted answer, so the calibration fits the record rather than predicting it. Treat it as a consistency check. New, out-of-sample observations (an S1677 floor vote, Gov. Sherrill's signature) would be the real test.", ""];
})(),
...(() => {
  const tuned = prefs.withEvidence(m, ev), lams = [2, 4, 8, 16];
  const row = (name, model) => `| ${name} | ` + lams.map(l => { const q = g.solveQR(model, { lambda: l }).law.s1677; return `${q.toFixed(2)} (log-loss ${(-Math.log(q)).toFixed(2)})`; }).join(" | ") + " |";
  const q8 = g.solveQR(tuned, { lambda: 8 });
  const top = Object.entries(q8.paths).sort((a, b) => b[1] - a[1]).slice(0, 4);
  return ["## Probabilistic play (logit quantal response)", "",
    "Movers don't always pick their best option. The Legislature, Governor and City choose by logit, P ∝ exp(λ·U). λ is rationality: 0 is random, ∞ is the strict best choice. Operators keep their pure Nash equilibrium, because firms optimize harder than political bodies. Grading becomes the probability the model gave to what actually happened.", "",
    "| P(committee picks S1677) | " + lams.map(l => `λ=${l}`).join(" | ") + " |", "|---|" + lams.map(() => ":-:").join("|") + "|",
    row("Raw weights", m), row("Calibrated (Beli answers)", tuned), "",
    "Most likely paths, calibrated, λ=8: " + top.map(([k, v]) => `${k.replace(/\|/g, " → ")} **${(v * 100).toFixed(0)}%**`).join("; ") + ".", "",
    "λ cannot be fitted from one vote; λ=8 is the default, and the sweep shows the calibrated model wins at every λ.", ""];
})(),
"## What the model says", "",
`1. **The committee's choice reveals a risk premium.** Every actor except gig drivers scores the amended bill higher, because the benefits scale with how long cars run driverless. Yet the Senate committee advanced S1677 with a 5-0 vote. The model reproduces that only if the Legislature puts at least **${tRisk.toFixed(2)}** weight on backlash risk, the chance a serious crash forces a Cruise-style halt. That is the real price of the human-driver phase.`,
`2. **Tesla's swing variable is evidence, not lobbying.** Take the Legislature's revealed risk weight of 0.30. Once Tesla's halt chance drops below **${(1 - tTes).toFixed(2)}** per driverless window, the Legislature itself prefers letting Tesla in, because then the amended bill wins. Owner lobbying moves nothing in this model. Verified crash data published through NHTSA would.`,
`3. **The Governor is not the bottleneck.** She keeps signing the amended bill unless her weight on driver jobs passes **${tJobs ? tJobs.toFixed(2) : "never"}**, far above any stated priority.`,
`4. **The city holds a quiet veto.** With a restricted curb under S1677, Waymo ${restrict.waymo ? "still enters" : "**stays out**"}: the expected revenue no longer covers the entry cost. The Mayor's best response is a **managed curb** in every branch. The city takes curb fees plus Via integration savings of about $1-3M/yr against a ~$90M deficit, and trades access for safety rules.`,
"5. **Via is the city's lever on the budget.** Via only integrates when Waymo is in and the curb is not restricted. That makes Via the bridge between the Mayor's budget priority and Waymo's entry. The Chandler, AZ model is the playbook.", "",
"## Limits", "",
"- Effect sizes and weights are assumptions anchored to sources (see `model.json` → `basis`/`src` for each block). They are not measurements.",
"- Halt hazards are assumptions; there is no public per-mile crash rate for Tesla Robotaxi.",
"- One-shot game. Repeated play (pilot renewals, the 2029 sunset) and side payments (labor transition funds) are not modeled.", "",
].join("\n");
fs.writeFileSync(here("GAME.md"), md);
console.log("built index.html + GAME.md", { eq: g.pathKey(s.eq), tRisk, tJobs, tTes: 1 - tTes });
