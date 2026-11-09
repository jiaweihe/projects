// node build.js  -> index.html (interactive page) + GAME.md (static summary)
const fs = require("fs"), path = require("path");
const g = require("./solver.js"), m = require("./model.json");
const here = f => path.join(__dirname, f);

const page = fs.readFileSync(here("page.template.html"), "utf8")
  .replace("/*SOLVER*/", () => fs.readFileSync(here("solver.js"), "utf8"))
  .replace("/*MODEL*/", () => JSON.stringify(m));
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
