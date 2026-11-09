// node --test   (from this folder)
const test = require("node:test");
const assert = require("node:assert/strict");
const g = require("./solver.js");
const m = require("./model.json");
const map = require("../stakeholders.json");

const base = g.solve(m);
const R = base.resolved;
const PROFILES = [...Array(8)].map((_, i) => ({ waymo: !!(i & 1), tesla: !!(i & 2), via: !!(i & 4) }));

test("weights sum to 1 and power matches the power map", () => {
  const power = Object.fromEntries(map.stakeholders.map(s => [s.id, s.power]));
  for (const [id, p] of Object.entries(m.players)) {
    assert.ok(Math.abs(Object.values(p.w).reduce((a, b) => a + b, 0) - 1) < 1e-9, id);
    assert.equal(p.power, power[id], id);
    for (const d of Object.keys(p.w)) assert.ok(d === "revenue" || g.DIMS.includes(d), `${id}.${d}`);
  }
});

test("every modeled block cites an https source and states its basis", () => {
  const blocks = [...Object.values(m.laws), ...Object.values(m.city), m.operators.waymo, m.operators.tesla, m.via];
  for (const b of blocks) {
    assert.ok(b.basis && b.basis.length > 20, b.label);
    assert.ok(b.src.length && b.src.every(u => u.startsWith("https://")), b.label);
  }
  assert.ok(m.risk_src.every(u => u.startsWith("https://")));
});

test("Tesla can only enter under the industry-amended bill", () => {
  for (const [law, b] of Object.entries(base.branches))
    if (b.law !== "amended") assert.equal(b.a.tesla, false, law);
});

test("operators play a pure Nash equilibrium in every law x curb subgame", () => {
  for (const law of Object.keys(R.laws)) for (const city of Object.keys(R.city)) {
    const ne = g.operatorsNE(R, law, city);
    assert.ok(ne.isNash, `${law}/${city} has no pure NE`);
    const u = g.utilities(R, g.outcome(R, law, city, ne.a));
    for (const k of g.OPS) {
      const dev = { ...ne.a, [k]: !ne.a[k] };
      if (!g.feasible(R, law, dev)) continue;
      assert.ok(g.utilities(R, g.outcome(R, law, city, dev))[k] <= u[k] + 1e-9, `${law}/${city}: ${k} deviates`);
    }
  }
});

test("backward induction: each mover best-responds", () => {
  for (const b of Object.values(base.branches)) for (const city of Object.keys(R.city)) {
    const ne = g.operatorsNE(R, b.law, city);
    assert.ok(g.utilities(R, g.outcome(R, b.law, city, ne.a)).mayor_solomon <= b.u.mayor_solomon + 1e-9);
  }
  for (const b of Object.values(base.branches)) assert.ok(b.u.zwicker <= base.eq.u.zwicker + 1e-9);
  const vetoU = g.cityStage(R, "stall").u.gov_sherrill;
  for (const b of Object.values(base.branches)) if (b.proposed !== "stall")
    assert.equal(b.sign, g.cityStage(R, b.proposed).u.gov_sherrill >= vetoU - 1e-9, b.proposed);
});

test("no AVs means no AV effects: stall is the zero point", () => {
  const o = g.outcome(R, "stall", "managed", { waymo: false, tesla: false, via: false });
  for (const d of g.DIMS) assert.equal(o.v[d], 0, d);
});

test("halt risk falls as the law validates more", () => {
  const all = { waymo: true, tesla: true, via: false };
  const lo = { ...R, laws: { ...R.laws, x: { ...R.laws.amended, valid: 0.1 } } };
  const hi = { ...R, laws: { ...R.laws, x: { ...R.laws.amended, valid: 0.7 } } };
  assert.ok(g.outcome(lo, "x", "open", all).pHalt > g.outcome(hi, "x", "open", all).pHalt);
});

test("robustness is deterministic and sums to 1", () => {
  const a = g.robustness(m, 300, 11), b = g.robustness(m, 300, 11);
  assert.deepEqual(a, b);
  assert.ok(Math.abs(a.reduce((s, x) => s + x.share, 0) - 1) < 1e-9);
});

test("regression: baseline result and revealed-preference threshold", () => {
  assert.equal(g.pathKey(base.eq), "amended|signed|managed|waymo+tesla+via");
  const t = g.threshold(x => g.setWeight(m, "zwicker", "risk", x), eq => eq.law === "s1677", 0, 0.8);
  assert.ok(t > 0.2 && t < 0.35, `threshold ${t}`);
});
