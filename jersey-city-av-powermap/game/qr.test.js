const test = require("node:test");
const assert = require("node:assert/strict");
const g = require("./solver.js");
const p = require("./prefs.js");
const m = require("./model.json");
const ev = require("./evidence.json");

const sum = o => Object.values(o).reduce((a, b) => a + b, 0);

test("law and path probabilities each sum to 1", () => {
  const q = g.solveQR(m, { lambda: 8 });
  assert.ok(Math.abs(sum(q.law) - 1) < 1e-9);
  assert.ok(Math.abs(sum(q.paths) - 1) < 1e-9);
});

test("lambda = 0 makes every bill equally likely", () => {
  const q = g.solveQR(m, { lambda: 0 });
  for (const v of Object.values(q.law)) assert.ok(Math.abs(v - 0.25) < 1e-9);
});

test("a very large lambda recovers the argmax equilibrium", () => {
  for (const model of [m, p.withEvidence(m, ev)]) {
    const q = g.solveQR(model, { lambda: 2000 });
    assert.ok(q.paths[g.pathKey(g.solve(model).eq)] > 0.99);
  }
});

test("more Legislature weight on backlash risk raises P(S1677)", () => {
  const lo = g.solveQR(g.setWeight(m, "zwicker", "risk", 0.1), { lambda: 8 }).law.s1677;
  const hi = g.solveQR(g.setWeight(m, "zwicker", "risk", 0.4), { lambda: 8 }).law.s1677;
  assert.ok(hi > lo, `${lo} !< ${hi}`);
});

test("calibrated weights assign more probability to what the committee actually did", () => {
  const raw = g.solveQR(m, { lambda: 8 }).law.s1677;
  const tuned = g.solveQR(p.withEvidence(m, ev), { lambda: 8 }).law.s1677;
  assert.ok(tuned > raw && tuned > 0.5, `${raw} -> ${tuned}`);
});

test("calibration lowers log-loss on the committee vote at every rationality level", () => {
  const tuned = p.withEvidence(m, ev);
  for (const lambda of [2, 4, 8, 16]) {
    const raw = -Math.log(g.solveQR(m, { lambda }).law.s1677), cal = -Math.log(g.solveQR(tuned, { lambda }).law.s1677);
    assert.ok(cal < raw, `lambda ${lambda}: ${raw.toFixed(3)} -> ${cal.toFixed(3)}`);
  }
});

test("Governor's sign probability is 1 for stall and in (0,1) otherwise", () => {
  const q = g.solveQR(m, { lambda: 8 });
  assert.equal(q.sign.stall, 1);
  for (const l of ["s1677", "amended", "moratorium"]) assert.ok(q.sign[l] > 0 && q.sign[l] < 1, l);
});
