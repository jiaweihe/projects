const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("./launch.js");
const m = require("./model.json");

const base = L.solveLaunch(m);

test("each regime yields a full path: operators -> city -> state", () => {
  for (const reg of ["gap", "s1677"]) {
    const e = base.regimes[reg];
    for (const k of ["waymo", "tesla"]) assert.ok(["wait", "test", "driverless"].includes(e.ops[k]), `${reg}.${k}`);
    assert.ok(["open", "managed", "restrict"].includes(e.city));
    assert.ok(["tolerate", "conditions", "halt"].includes(e.state));
  }
});

test("Tesla cannot run driverless under S1677 but can in the legal gap", () => {
  assert.equal(L.feasible(m, "s1677", { waymo: "wait", tesla: "driverless" }), false);
  assert.equal(L.feasible(m, "gap", { waymo: "wait", tesla: "driverless" }), true);
});

test("operators: pure Nash where one exists (S1677); logit equilibrium fixed point everywhere", () => {
  const r = L.resolveLaunch(m);
  const e = L.solveRegime(r, "s1677", m, 2000);
  for (const k of ["waymo", "tesla"]) for (const alt of ["wait", "test", "driverless"]) {
    const dev = { ...e.ops, [k]: alt };
    if (!L.feasible(m, "s1677", dev)) continue;
    assert.ok(L.continuation(r, "s1677", dev).u[k] <= e.u[k] + 1e-9, `s1677: ${k} -> ${alt}`);
  }
  for (const reg of ["gap", "s1677"]) {
    const q = L.solveRegime(r, reg, m);
    assert.ok(q.resid < 1e-8, `${reg} not converged`);
    for (const k of ["waymo", "tesla"]) assert.ok(Math.abs(Object.values(q.mix[k]).reduce((a, b) => a + b, 0) - 1) < 1e-9);
    assert.ok(Math.abs(q.profiles.reduce((a, x) => a + x.prob, 0) - 1) < 1e-9);
  }
});

test("in the legal gap no pure equilibrium exists at midpoints, so the operators mix", () => {
  const q = L.solveRegime(L.resolveLaunch(m), "gap", m);
  const maxP = Math.max(...Object.values(q.mix.waymo));
  assert.ok(maxP < 0.99, `Waymo plays a pure strategy (${maxP})`);
});

test("the State best-responds and halting nobody changes nothing", () => {
  const r = L.resolveLaunch(m);
  const ops = { waymo: "test", tesla: "wait" };
  const a = L.terminal(r, "gap", ops, "managed", "halt"), b = L.terminal(r, "gap", ops, "managed", "tolerate");
  for (const d of Object.keys(a.v)) if (d !== "innovation") assert.equal(a.v[d], b.v[d], d);
  const e = L.solveRegime(r, "gap", m), st = L.stateBest(r, "gap", e.ops, e.city);
  assert.equal(st.state, e.state);
});

test("headline probabilities are well-formed and blend the two regimes", () => {
  const h = L.outlook(m, 400, 5);
  for (const k of ["waymo_driverless", "tesla_driverless", "any_driverless", "any_operating", "halted"]) assert.ok(h[k] >= 0 && h[k] <= 1, k);
  assert.ok(h.any_operating >= h.any_driverless);
});

test("a stronger halt power lowers the chance of driverless service", () => {
  const weak = JSON.parse(JSON.stringify(m)), strong = JSON.parse(JSON.stringify(m));
  weak.launch.regimes.gap.halt_success = [0.1, 0.1];
  strong.launch.regimes.gap.halt_success = [1, 1];
  assert.ok(L.outlook(strong, 400, 5).any_driverless <= L.outlook(weak, 400, 5).any_driverless);
});

test("observed 2026: under today's legal gap Waymo tests but does not launch driverless", () => {
  const s = L.solveLaunch(m, { year: "2026" });
  assert.notEqual(s.regimes.gap.ops.waymo, "driverless");
});

test("2027 readiness raises the chance of driverless service vs 2026", () => {
  assert.ok(L.outlook(m, 300, 5, 0.5, "2027").any_driverless >= L.outlook(m, 300, 5, 0.5, "2026").any_driverless);
});

test("the permission-first cost only applies without a statute", () => {
  const r = L.resolveLaunch(m, null, 0, "2027");
  const ops = { waymo: "driverless", tesla: "wait" };
  const gap = L.terminal(r, "gap", ops, "managed", "tolerate").rev.waymo;
  const r2 = JSON.parse(JSON.stringify(m)); r2.launch.permissionless_cost.waymo = [0, 0];
  const gap0 = L.terminal(L.resolveLaunch(r2, null, 0, "2027"), "gap", ops, "managed", "tolerate").rev.waymo;
  assert.ok(gap < gap0);
});

test("observed: the State tolerates autonomous operation in JC's legal gap (delivery robots since 2025, even after an injury)", () => {
  assert.ok(m.launch.basis.includes("delivery robots"));
  const h = L.outlook(m, 300, 5, 0.5, "2027");
  assert.ok(h.halted < 0.05, `deliberate halt ${h.halted}`);
});
