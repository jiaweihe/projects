// 2027 launch game: will AVs operate in Jersey City in 2027, whatever happens to S1677?
// Order (solved backwards): Waymo & Tesla pick wait / test / driverless at the same time ->
// the City sets curb policy -> the State (Governor + MVC) tolerates, imposes conditions, or halts.
// Played under two legal regimes, "gap" (no statute, today) and "s1677" (enacted), blended by P(bill).
(function (root) {
  const g = typeof require === "function" ? require("./solver.js") : root.AVGame;
  const MODES = ["wait", "test", "driverless"], OPS2 = ["waymo", "tesla"];
  const STATES = ["tolerate", "conditions", "halt"];
  const pick = (v, rng) => Array.isArray(v) ? (rng ? v[0] + (v[1] - v[0]) * rng() : (v[0] + v[1]) / 2) : v;

  function resolveLaunch(m, rng = null, jitter = 0, year = "2027") {
    const r = g.resolve(m, rng, jitter), L = m.launch;
    r.L = { year, ready: pick(L.readiness[year], rng),
      permit: { waymo: pick(L.permissionless_cost.waymo, rng), tesla: pick(L.permissionless_cost.tesla, rng) },
      test: pick(L.test_value, rng), brand: pick(L.halt_brand_penalty, rng), haltInnov: pick(L.halt_innovation_cost, rng),
      pBill: pick(L.p_bill, rng), statePlayers: L.state_players, regimes: {} };
    for (const [k, reg] of Object.entries(L.regimes)) r.L.regimes[k] = { ...reg, q: pick(reg.halt_success, rng) };
    return r;
  }

  const feasible = (m, reg, ops) => !(ops.tesla === "driverless" && !m.launch.regimes[reg].tesla_driverless);

  function terminal(r, reg, ops, city, state) {
    const R = r.L.regimes[reg], st = R.state[state], C = r.city[city];
    const v = Object.fromEntries(g.DIMS.map(d => [d, 0])), rev = { waymo: 0, tesla: 0, via: 0 };
    const add = (eff, k) => { for (const d in eff) v[d] += eff[d] * k; };
    const share = {};
    for (const k of OPS2) share[k] = ops[k] !== "driverless" ? 0
      : r.L.ready * (state === "halt" ? (1 - R.q) * R.state.tolerate.share : st.share);
    const pHalt = Math.min(0.9, OPS2.reduce((s, k) => s + r.ops[k].hazard * share[k] * (1 - st.valid), 0));
    const keep = Object.fromEntries(OPS2.map(k => [k, share[k] * (1 - pHalt / 2)]));
    const anyDriverless = OPS2.some(k => ops[k] === "driverless");
    for (const k of OPS2) {
      if (ops[k] === "test") { rev[k] += r.L.test; v.innovation += 0.05; }
      if (ops[k] !== "driverless") continue;
      add(r.ops[k].fx, keep[k]);
      rev[k] = r.ops[k].revenue * keep[k] * C.mult - r.ops[k].cost - (state === "halt" ? R.q * r.L.brand : 0)
        - (reg === "gap" ? r.L.permit[k] : 0); // no statute = no explicit authorization
    }
    if (ops.waymo === "driverless" && ops.tesla === "driverless") v.jobs += r.bothOffset * Math.min(keep.waymo, keep.tesla);
    const kmax = Math.max(keep.waymo, keep.tesla);
    if (kmax > 0) add(C.fx, kmax);
    if (keep.waymo > 0 && city !== "restrict") { add(r.via.fx, keep.waymo); rev.via = r.via.revenue * keep.waymo; rev.waymo += 0.2 * keep.waymo; }
    if (state === "halt" && anyDriverless) v.innovation -= r.L.haltInnov;
    v.risk = pHalt ? -2 * pHalt : 0;
    for (const d of g.DIMS) v[d] = Math.max(-2, Math.min(2, v[d]));
    return { v, rev, pHalt, keep };
  }

  const raw = (p, id, o) => Object.entries(p.w).reduce((s, [d, w]) => s + w * (d === "revenue" ? (o.rev[id] || 0) : o.v[d]), 0);
  const PROFILES = MODES.flatMap(a => MODES.map(b => ({ waymo: a, tesla: b })));

  function scales(r) {
    if (r._lscale) return r._lscale;
    const s = Object.fromEntries(Object.keys(r.players).map(k => [k, 1e-9]));
    for (const reg of Object.keys(r.L.regimes)) for (const ops of PROFILES) for (const city of Object.keys(r.city)) for (const st of STATES) {
      const o = terminal(r, reg, ops, city, st);
      for (const [id, p] of Object.entries(r.players)) s[id] = Math.max(s[id], Math.abs(raw(p, id, o)));
    }
    return (r._lscale = s);
  }

  function utilities(r, o) {
    const s = scales(r), u = {};
    for (const [id, p] of Object.entries(r.players)) u[id] = raw(p, id, o) / s[id];
    for (const [id, p] of Object.entries(r.players)) if (p.coalition != null) {
      let num = 0, den = 0;
      for (const [j, q] of Object.entries(r.players)) if (j !== id) { num += q.power * u[j]; den += q.power; }
      u[id] = (1 - p.coalition) * u[id] + p.coalition * (num / den);
    }
    u.state = Object.entries(r.L.statePlayers).reduce((a, [id, w]) => a + w * u[id], 0);
    return u;
  }

  function argmax(xs, f) { return xs.reduce((best, x) => (best == null || f(x) > f(best) + 1e-9 ? x : best), null); }

  function stateBest(r, reg, ops, city) {
    const rows = STATES.map(state => { const o = terminal(r, reg, ops, city, state); return { state, o, u: utilities(r, o) }; });
    return argmax(rows, x => x.u.state);
  }

  function continuation(r, reg, ops) {
    const rows = Object.keys(r.city).map(city => ({ city, ...stateBest(r, reg, ops, city) }));
    const best = argmax(rows, x => x.u.mayor_solomon);
    return { ops, ...best };
  }

  // Operators move simultaneously. Pure equilibria don't always exist (in the gap, Waymo would rather
  // test whenever Tesla launches, and vice versa), so we solve a logit quantal-response equilibrium:
  // each operator's mode probabilities are a softmax best response to the other's. Large lambda
  // approaches a mixed Nash equilibrium. City and State respond to the realized profile.
  function solveRegime(r, reg, m = null, lambda = 12) {
    const ok = ops => (m ? feasible(m, reg, ops) : !(ops.tesla === "driverless" && !r.L.regimes[reg].tesla_driverless));
    const cont = {};
    for (const p of PROFILES) if (ok(p)) cont[p.waymo + "|" + p.tesla] = continuation(r, reg, p);
    const avail = k => MODES.filter(x => ok(k === "waymo" ? { waymo: x, tesla: "wait" } : { waymo: "wait", tesla: x }));
    const P = { waymo: Object.fromEntries(avail("waymo").map(x => [x, 1 / avail("waymo").length])),
                tesla: Object.fromEntries(avail("tesla").map(x => [x, 1 / avail("tesla").length])) };
    const eu = (k, x, Q) => { const o = k === "waymo" ? "tesla" : "waymo";
      return Object.entries(Q[o]).reduce((s, [y, q]) => s + q * cont[k === "waymo" ? x + "|" + y : y + "|" + x].u[k], 0); };
    let resid = 1;
    for (let it = 0; it < 2000 && resid > 1e-10; it++) {
      resid = 0;
      for (const k of OPS2) {
        const xs = Object.keys(P[k]), pr = g.softmax(xs.map(x => eu(k, x, P)), lambda);
        xs.forEach((x, i) => { const nv = 0.5 * P[k][x] + 0.5 * pr[i]; resid = Math.max(resid, Math.abs(nv - P[k][x])); P[k][x] = nv; });
      }
    }
    const profiles = Object.entries(cont).map(([key, c]) => { const [w, te] = key.split("|"); return { ...c, prob: (P.waymo[w] || 0) * (P.tesla[te] || 0) }; });
    const modal = profiles.reduce((a, b) => (b.prob > a.prob ? b : a));
    return { ...modal, mix: P, profiles, resid };
  }

  function solveLaunch(m, opts = {}) {
    const r = resolveLaunch(m, opts.rng || null, opts.jitter || 0, opts.year || "2027");
    return { regimes: { gap: solveRegime(r, "gap", m), s1677: solveRegime(r, "s1677", m) }, pBill: r.L.pBill, resolved: r };
  }

  // Monte Carlo over every sourced range (+/- jitter on weights), blending regimes by P(bill).
  function outlook(m, n = 1000, seed = 7, jitter = 0.5, year = "2027") {
    const rng = g.rngFrom(seed), acc = { waymo_driverless: 0, tesla_driverless: 0, any_driverless: 0, any_operating: 0, halted: 0, crash_halt: 0 };
    const paths = {};
    for (let i = 0; i < n; i++) {
      const s = solveLaunch(m, { rng, jitter, year });
      for (const [reg, w] of [["gap", 1 - s.pBill], ["s1677", s.pBill]]) for (const e of s.regimes[reg].profiles) {
        const pw = w * e.prob; if (!pw) continue;
        const dl = OPS2.filter(k => e.ops[k] === "driverless" && e.o.keep[k] > 0);
        acc.waymo_driverless += pw * (dl.includes("waymo") ? 1 : 0);
        acc.tesla_driverless += pw * (dl.includes("tesla") ? 1 : 0);
        acc.any_driverless += pw * (dl.length ? 1 : 0);
        acc.any_operating += pw * (OPS2.some(k => e.ops[k] === "test" || (e.ops[k] === "driverless" && e.o.keep[k] > 0)) ? 1 : 0);
        acc.halted += pw * (e.state === "halt" && OPS2.some(k => e.ops[k] === "driverless") ? 1 : 0);
        acc.crash_halt += pw * e.o.pHalt;
        const key = `${reg}|${e.ops.waymo}|${e.ops.tesla}|${e.city}|${e.state}`;
        paths[key] = (paths[key] || 0) + pw;
      }
    }
    for (const k in acc) acc[k] /= n;
    acc.paths = Object.entries(paths).map(([k, v]) => ({ path: k, share: v / n })).sort((a, b) => b.share - a.share);
    return acc;
  }

  const api = { MODES, STATES, resolveLaunch, feasible, terminal, utilities, stateBest, continuation, solveRegime, solveLaunch, outlook };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.AVLaunch = api;
})(typeof window !== "undefined" ? window : globalThis);
