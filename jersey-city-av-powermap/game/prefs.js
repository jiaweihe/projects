// Beli-style preference learning. People answer quick Boolean questions ("for the Mayor, does
// safety matter more than budget?"), and weights are fitted with a Bradley–Terry model:
//   P(a beats b) = w_a / (w_a + w_b)
// The current weights act as a Gamma prior worth `alpha` pseudo-comparisons, so a few answers
// nudge the weights and many answers dominate. Fitting uses Hunter's (2004) MM algorithm for the MAP estimate.
(function (root) {
  const NEW_DIM_PRIOR = 0.02; // prior mass for a dimension the actor did not weight before

  const winsOf = (c, d) => (c.win === "tie" ? 0.5 : (c.win === "a" ? c.a : c.b) === d ? 1 : 0);

  /** @param {Record<string, number>} prior @param {{a:string,b:string,win:"a"|"b"|"tie"}[]} comps @param {number} alpha */
  function fitWeights(prior, comps, alpha = 4) {
    alpha = Math.max(alpha, 1e-6); // a prior of zero would leave unasked dimensions undefined
    comps = comps.filter(c => c.a !== c.b);
    for (const c of comps) if (!["a", "b", "tie"].includes(c.win)) throw new Error(`win must be a, b or tie (got ${c.win})`);
    const p = { ...prior };
    for (const c of comps) for (const d of [c.a, c.b]) if (!(d in p)) p[d] = NEW_DIM_PRIOR;
    const z = Object.values(p).reduce((a, b) => a + b, 0);
    for (const d in p) p[d] /= z;
    let s = { ...p };
    for (let it = 0; it < 500; it++) {
      /** @type {Record<string, number>} */
      const next = {};
      let delta = 0;
      for (const d in p) {
        let wins = 0, denom = 0;
        for (const c of comps) if (c.a === d || c.b === d) {
          wins += winsOf(c, d);
          denom += 1 / (s[c.a] + s[c.b]);
        }
        next[d] = (alpha * p[d] + wins) / (alpha + denom);
        delta = Math.max(delta, Math.abs(next[d] - s[d]));
      }
      s = next;
      if (delta < 1e-12) break;
    }
    const t = Object.values(s).reduce((a, b) => a + b, 0);
    return Object.fromEntries(Object.entries(s).map(([d, v]) => [d, v / t]));
  }

  // Simulated respondent who answers according to Bradley–Terry with the given true weights.
  function simulate(truth, n, rng) {
    const dims = Object.keys(truth), out = [];
    for (let i = 0; i < n; i++) {
      const i = Math.floor(rng() * dims.length);
      let j = Math.floor(rng() * (dims.length - 1));
      if (j >= i) j++; // uniform over the other dimensions
      const a = dims[i], b = dims[j];
      out.push({ a, b, win: rng() < truth[a] / (truth[a] + truth[b]) ? "a" : "b" });
    }
    return out;
  }

  // Ask the pair the model is least sure about, discounted by how often it was asked already.
  function nextPair(w, comps) {
    const dims = Object.keys(w);
    let best = null;
    for (let i = 0; i < dims.length; i++) for (let j = i + 1; j < dims.length; j++) {
      const a = dims[i], b = dims[j], pa = w[a] / (w[a] + w[b]);
      const n = comps.filter(c => (c.a === a && c.b === b) || (c.a === b && c.b === a)).length;
      const score = (pa * (1 - pa)) / (1 + n);
      if (!best || score > best.score + 1e-12) best = { a, b, score };
    }
    return best;
  }

  // Beli's ranking move: binary-insert `item` into a best-first `order` using a Boolean `better(x, y)`.
  function insertRank(order, item, better) {
    let lo = 0, hi = order.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (better(item, order[mid])) hi = mid; else lo = mid + 1; }
    return [...order.slice(0, lo), item, ...order.slice(lo)];
  }

  // Apply answers per actor ({ actorId: comps[] }) to a copy of the model.
  function applyComparisons(model, byActor, alpha = 4) {
    const out = JSON.parse(JSON.stringify(model));
    for (const [id, comps] of Object.entries(byActor)) if (out.players[id] && comps.length)
      out.players[id].w = fitWeights(out.players[id].w, comps, alpha);
    return out;
  }

  // Calibrate a model with the sourced revealed-preference answers in evidence.json.
  const withEvidence = (model, evidence) => applyComparisons(model, evidence.comparisons, evidence.alpha);

  const api = { withEvidence, fitWeights, simulate, nextPair, insertRank, applyComparisons };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.AVPrefs = api;
})(typeof window !== "undefined" ? window : globalThis);
