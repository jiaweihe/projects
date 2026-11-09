// Sequential AV game for Jersey City, solved by backward induction.
// Legislature picks a bill -> Governor signs/vetoes -> City sets curb policy ->
// Waymo, Tesla, Via move simultaneously (pure-strategy Nash equilibrium).
// Works in Node (module.exports) and the browser (window.AVGame).
(function (root) {
  const DIMS = ["safety", "risk", "jobs", "budget", "access", "innovation"];
  const OPS = ["waymo", "tesla", "via"];

  function rngFrom(seed) { // mulberry32: deterministic for tests
    let a = seed >>> 0;
    return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  const pick = (v, rng) => Array.isArray(v) ? (rng ? v[0] + (v[1] - v[0]) * rng() : (v[0] + v[1]) / 2) : v;
  const fx = (eff, rng) => Object.fromEntries(Object.entries(eff || {}).map(([k, v]) => [k, pick(v, rng)]));

  // Collapse every [lo, hi] range to a number: midpoint, or a random draw when rng is given.
  // jitter > 0 also scales each player weight by U(1-jitter, 1+jitter) and renormalises.
  function resolve(m, rng = null, jitter = 0) {
    const r = { laws: {}, city: {}, players: {} };
    for (const [k, l] of Object.entries(m.laws)) r.laws[k] = { ...l, share: pick(l.driverless_share, rng), valid: pick(l.validation, rng), fx: fx(l.effects, rng) };
    for (const [k, c] of Object.entries(m.city)) r.city[k] = { ...c, fx: fx(c.effects, rng), mult: pick(c.op_revenue, rng) };
    r.ops = {};
    for (const k of ["waymo", "tesla"]) { const o = m.operators[k];
      r.ops[k] = { fx: fx(o.effects, rng), hazard: pick(o.hazard, rng),
        revenue: pick(o.revenue, rng), cost: pick(o.entry_cost, rng) }; }
    r.bothOffset = pick(m.operators.both_jobs_offset, rng);
    r.via = { fx: fx(m.via.effects, rng), revenue: pick(m.via.revenue, rng), failed: pick(m.via.failed_cost, rng) };
    for (const [k, p] of Object.entries(m.players)) {
      let w = { ...p.w };
      if (rng && jitter) { for (const d in w) w[d] *= 1 - jitter + 2 * jitter * rng();
        const s = Object.values(w).reduce((a, b) => a + b, 0); for (const d in w) w[d] /= s; }
      r.players[k] = { ...p, w };
    }
    return r;
  }

  function feasible(r, law, a) {
    return (!a.waymo || r.laws[law].waymo) && (!a.tesla || r.laws[law].tesla);
  }

  function outcome(r, law, city, a) {
    const v = Object.fromEntries(DIMS.map(d => [d, 0]));
    const add = (eff, k = 1) => { for (const d in eff) v[d] += eff[d] * k; };
    const L = r.laws[law], C = r.city[city], share = L.share;
    // Chance a serious crash forces an MVC halt (Cruise 2023 precedent); a halt costs ~half the window.
    const pHalt = Math.min(0.9, ["waymo", "tesla"].reduce((s, k) => s + (a[k] ? r.ops[k].hazard * share * (1 - L.valid) : 0), 0));
    const keep = share * (1 - pHalt / 2);
    add(L.fx);
    v.risk = pHalt ? -2 * pHalt : 0;
    if (a.waymo || a.tesla) add(C.fx, keep); // curb policy only matters once AVs are on the street
    const rev = { waymo: 0, tesla: 0, via: 0 };
    for (const k of ["waymo", "tesla"]) if (a[k]) {
      add(r.ops[k].fx, keep);
      rev[k] = r.ops[k].revenue * keep * C.mult - r.ops[k].cost;
    }
    if (a.waymo && a.tesla) v.jobs += r.bothOffset * keep; // displacement is not fully additive
    const integrated = a.via && a.waymo && city !== "restrict";
    if (a.via) {
      if (integrated) { add(r.via.fx, keep); rev.via = r.via.revenue * keep; rev.waymo += 0.2 * keep; }
      else rev.via = -r.via.failed;
    }
    for (const d of DIMS) v[d] = Math.max(-2, Math.min(2, v[d]));
    return { v, rev, integrated, pHalt };
  }

  const own = (p, id, o) => Object.entries(p.w).reduce((s, [d, w]) => s + w * (d === "revenue" ? (o.rev[id] || 0) : o.v[d]), 0);

  // Largest |raw utility| per actor over every reachable outcome, so utilities are comparable.
  function scales(r) {
    if (r._scale) return r._scale;
    const s = Object.fromEntries(Object.keys(r.players).map(k => [k, 1e-9]));
    for (const law of Object.keys(r.laws)) for (const city of Object.keys(r.city)) for (let i = 0; i < 8; i++) {
      const a = { waymo: !!(i & 1), tesla: !!(i & 2), via: !!(i & 4) };
      if (!feasible(r, law, a)) continue;
      const o = outcome(r, law, city, a);
      for (const [id, p] of Object.entries(r.players)) s[id] = Math.max(s[id], Math.abs(own(p, id, o)));
    }
    return (r._scale = s);
  }

  function utilities(r, o) {
    const u = {}, s = scales(r);
    for (const [id, p] of Object.entries(r.players)) u[id] = own(p, id, o) / s[id];
    for (const [id, p] of Object.entries(r.players)) if (p.coalition != null) {
      let num = 0, den = 0;
      for (const [j, q] of Object.entries(r.players)) if (j !== id) { num += q.power * u[j]; den += q.power; }
      u[id] = (1 - p.coalition) * u[id] + p.coalition * (num / den);
    }
    return u;
  }

  // Operators' simultaneous move: enumerate the 8 profiles, keep pure Nash equilibria,
  // select the one with the highest joint operator payoff (payoff-dominance).
  function operatorsNE(r, law, city) {
    const profiles = [];
    for (let i = 0; i < 8; i++) {
      const a = { waymo: !!(i & 1), tesla: !!(i & 2), via: !!(i & 4) };
      if (feasible(r, law, a)) profiles.push(a);
    }
    const val = a => utilities(r, outcome(r, law, city, a));
    const eq = profiles.filter(a => { const u = val(a);
      return OPS.every(k => { const b = { ...a, [k]: !a[k] };
        return !feasible(r, law, b) || val(b)[k] <= u[k] + 1e-9; }); });
    const pool = eq.length ? eq : profiles;
    const score = a => { const u = val(a); return OPS.reduce((s, k) => s + u[k], 0); };
    const best = pool.reduce((x, y) => (score(y) > score(x) + 1e-9 ? y : x));
    return { a: best, isNash: eq.length > 0, nEq: eq.length };
  }

  function cityStage(r, law) {
    let best = null;
    for (const city of Object.keys(r.city)) {
      const ne = operatorsNE(r, law, city), o = outcome(r, law, city, ne.a), u = utilities(r, o);
      if (!best || u.mayor_solomon > best.u.mayor_solomon + 1e-9) best = { law, city, ...ne, o, u };
    }
    return best;
  }

  function solve(m, opts = {}) {
    const r = opts.resolved || resolve(m, opts.rng || null, opts.jitter || 0);
    const branches = {};
    for (const law of Object.keys(r.laws)) {
      const signed = cityStage(r, law);
      const vetoed = cityStage(r, "stall");
      const sign = law === "stall" || signed.u.gov_sherrill >= vetoed.u.gov_sherrill - 1e-9;
      branches[law] = { proposed: law, sign, ...(sign ? signed : vetoed) };
    }
    const lawChoice = Object.keys(branches).reduce((x, y) =>
      branches[y].u.zwicker > branches[x].u.zwicker + 1e-9 ? y : x);
    return { eq: branches[lawChoice], branches, resolved: r };
  }

  const pathKey = e => `${e.proposed}|${e.sign ? "signed" : "vetoed"}|${e.city}|` +
    (OPS.filter(k => e.a[k]).join("+") || "no entry");

  function robustness(m, n = 1000, seed = 7, jitter = 0.5) {
    const rng = rngFrom(seed), counts = {};
    for (let i = 0; i < n; i++) { const k = pathKey(solve(m, { rng, jitter }).eq); counts[k] = (counts[k] || 0) + 1; }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, c]) => ({ path: k, share: c / n }));
  }

  // Re-weight one actor so `dim` gets weight x and the others keep their relative shares.
  function setWeight(m, id, dim, x) {
    const c = JSON.parse(JSON.stringify(m)), w = c.players[id].w, rest = 1 - (w[dim] || 0);
    for (const d in w) if (d !== dim) w[d] = rest > 0 ? w[d] * (1 - x) / rest : (1 - x) / (Object.keys(w).length - 1);
    w[dim] = x;
    return c;
  }

  // Smallest x in [lo, hi] at which `test(solve(make(x)).eq)` becomes true (bisection; assumes one flip).
  function threshold(make, test, lo = 0, hi = 1, steps = 30) {
    const at = x => test(solve(make(x)).eq);
    if (at(lo)) return lo;
    if (!at(hi)) return null;
    for (let i = 0; i < steps; i++) { const mid = (lo + hi) / 2; if (at(mid)) hi = mid; else lo = mid; }
    return hi;
  }

  const api = { setWeight, threshold, cityStage, DIMS, OPS, resolve, outcome, utilities, operatorsNE, solve, robustness, pathKey, rngFrom, feasible };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.AVGame = api;
})(typeof window !== "undefined" ? window : globalThis);
