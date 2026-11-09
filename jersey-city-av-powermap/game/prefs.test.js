const test = require("node:test");
const assert = require("node:assert/strict");
const p = require("./prefs.js");
const g = require("./solver.js");
const m = require("./model.json");

const TRUE = { safety: 0.5, budget: 0.3, access: 0.2 };
const PRIOR = { safety: 0.2, budget: 0.4, access: 0.4 };
const mae = (a, b) => Object.keys(b).reduce((s, k) => s + Math.abs((a[k] || 0) - b[k]), 0) / Object.keys(b).length;

test("no comparisons returns the prior unchanged", () => {
  const w = p.fitWeights(PRIOR, [], 4);
  for (const k in PRIOR) assert.ok(Math.abs(w[k] - PRIOR[k]) < 1e-9, k);
});

test("weights always sum to 1 and stay positive", () => {
  const w = p.fitWeights(PRIOR, [{ a: "safety", b: "budget", win: "a" }, { a: "access", b: "budget", win: "tie" }], 4);
  assert.ok(Math.abs(Object.values(w).reduce((x, y) => x + y, 0) - 1) < 1e-9);
  assert.ok(Object.values(w).every(x => x > 0));
});

test("a single 'A beats B' answer raises A relative to B", () => {
  const w = p.fitWeights(PRIOR, [{ a: "safety", b: "budget", win: "a" }], 4);
  assert.ok(w.safety / w.budget > PRIOR.safety / PRIOR.budget);
});

test("answers recover the true weights better than the prior", () => {
  const rng = g.rngFrom(3);
  const comps = p.simulate(TRUE, 30, rng);
  const before = mae(PRIOR, TRUE), after = mae(p.fitWeights(PRIOR, comps, 4), TRUE);
  assert.ok(after < before / 2, `MAE ${before.toFixed(3)} -> ${after.toFixed(3)}`);
});

test("nextPair asks the most uncertain, least-asked pair (Beli style)", () => {
  const q = p.nextPair({ safety: 0.34, budget: 0.33, access: 0.33 }, []);
  assert.ok(["budget|access", "access|budget"].includes(`${q.a}|${q.b}`), JSON.stringify(q));
  const asked = [{ a: "budget", b: "access", win: "a" }, { a: "budget", b: "access", win: "a" }];
  const q2 = p.nextPair({ safety: 0.34, budget: 0.33, access: 0.33 }, asked);
  assert.notEqual(`${q2.a}|${q2.b}`.split("|").sort().join(), "access,budget");
});

test("insertRank places an item with binary insertion in <= ceil(log2(n+1)) questions", () => {
  const truth = ["safety", "budget", "access", "jobs", "innovation", "risk", "congestion"];
  const order = ["safety", "access", "jobs", "risk", "congestion"];
  let asked = 0;
  const better = (x, y) => { asked++; return truth.indexOf(x) < truth.indexOf(y); };
  const out = p.insertRank(order, "budget", better);
  assert.deepEqual(out, ["safety", "budget", "access", "jobs", "risk", "congestion"]);
  assert.ok(asked <= Math.ceil(Math.log2(order.length + 1)), `asked ${asked}`);
});

test("applyComparisons re-weights only the named actor", () => {
  const out = p.applyComparisons(m, { mayor_solomon: [{ a: "safety", b: "budget", win: "a" }] }, 4);
  assert.ok(out.players.mayor_solomon.w.safety > m.players.mayor_solomon.w.safety);
  assert.deepEqual(out.players.waymo.w, m.players.waymo.w);
  assert.deepEqual(m.players.mayor_solomon.w, require("./model.json").players.mayor_solomon.w); // input not mutated
});

test("self-comparisons are ignored and bad answers are rejected", () => {
  const w = p.fitWeights(PRIOR, [{ a: "safety", b: "safety", win: "a" }], 4);
  for (const k in PRIOR) assert.ok(Math.abs(w[k] - PRIOR[k]) < 1e-9, k);
  assert.throws(() => p.fitWeights(PRIOR, [{ a: "safety", b: "budget", win: "left" }], 4), /win/);
});

test("alpha = 0 with no answers does not produce NaN", () => {
  const w = p.fitWeights(PRIOR, [], 0);
  assert.ok(Object.values(w).every(Number.isFinite));
});

test("simulate samples every pair evenly (no last-dimension bias)", () => {
  const comps = p.simulate({ a: 1, b: 1, c: 1, d: 1 }, 6000, g.rngFrom(9));
  const seen = { a: 0, b: 0, c: 0, d: 0 };
  for (const c of comps) { assert.notEqual(c.a, c.b); seen[c.a]++; seen[c.b]++; }
  for (const k in seen) assert.ok(Math.abs(seen[k] / 3000 - 1) < 0.08, `${k}: ${seen[k]}`);
});

const ev = require("./evidence.json");
const cal = require("./calibrate.js");

test("evidence answers are sourced, explained and name real dimensions", () => {
  const dims = new Set([...g.DIMS, "revenue"]);
  for (const [id, comps] of Object.entries(ev.comparisons)) {
    assert.ok(m.players[id], id);
    for (const c of comps) {
      assert.ok(dims.has(c.a) && dims.has(c.b) && c.a !== c.b, `${id}: ${c.a}/${c.b}`);
      assert.ok(["a", "b", "tie"].includes(c.win));
      assert.ok(c.src.startsWith("https://") && c.why.length > 20, id);
    }
  }
});

test("calibrating with evidence improves the observed-behavior fit", () => {
  const raw = cal.fit(m).passed, tuned = cal.fit(p.withEvidence(m, ev)).passed;
  assert.ok(tuned > raw, `${raw} -> ${tuned}`);
  assert.equal(tuned, cal.FACTS.length);
});

test("calibration holds for prior strengths up to alpha = 8 (sensitivity guard)", () => {
  for (const a of [1, 2, 4, 8]) assert.ok(cal.fit(p.applyComparisons(m, ev.comparisons, a)).passed >= 7, `alpha ${a}`);
});
