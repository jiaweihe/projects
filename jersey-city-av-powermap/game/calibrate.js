// Grading: how well does the model reproduce what real actors actually did?
// Each fact is a sourced observation plus a check against the solved game.
(function (root) {
  const g = typeof require === "function" ? require("./solver.js") : root.AVGame;

  const u = (B, id, law) => B[law].u[id];
  const FACTS = [
    { id: "committee_s1677", claim: "NJ Senate committee advanced S1677 (5-0), not the industry-amended bill",
      check: s => s.eq.law === "s1677",
      src: ["https://newjerseymonitor.com/2026/05/13/driverless-cars-nj-senate/"] },
    { id: "waymo_enters_s1677", claim: "Waymo is preparing to operate under S1677-style rules (mapping JC, Newark tests)",
      check: s => g.cityStage(s.resolved, "s1677").a.waymo === true, // the signed-S1677 subgame, even if vetoed on path
      src: ["https://nj1015.com/autonomous-vehicles-waymo-pilot-program/"] },
    { id: "waymo_wants_amend", claim: "Waymo wants the safety-driver phase removed (prefers amended)",
      check: s => u(s.branches, "waymo", "amended") > u(s.branches, "waymo", "s1677"),
      src: ["https://www.govtech.com/transportation/new-jersey-bill-could-put-the-brakes-on-autonomous-cabs"] },
    { id: "gig_prefers_stall", claim: "Gig-driver petitioners want AVs stopped in NJ",
      check: s => u(s.branches, "av_opposition", "stall") > Math.max(u(s.branches, "av_opposition", "s1677"), u(s.branches, "av_opposition", "amended")),
      src: ["https://actionnetwork.org/petitions/stop-waymos-autonomous-vehicles-from-spreading-in-new-jersey/"] },
    { id: "chamber_amend", claim: "Chamber of Progress supports S1677 only with loosening amendments",
      check: s => u(s.branches, "chamber_progress", "amended") > u(s.branches, "chamber_progress", "s1677"),
      src: ["https://progresschamber.org/resources/testimony-to-nj-lawmakers-support-and-amend-establishing-an-autonomous-vehicle-pilot-program-a-3968-s-1677/"] },
    { id: "disability_s1677", claim: "Blind/disability advocates and SAVE-US testified for S1677",
      check: s => u(s.branches, "disability_safety", "s1677") > u(s.branches, "disability_safety", "stall"),
      src: ["https://newjerseymonitor.com/2026/05/13/driverless-cars-nj-senate/"] },
    { id: "hochul_withdrew", claim: "NY Gov. Hochul withdrew her robotaxi-service plan (prefers stall to a loose law)",
      check: s => u(s.branches, "ny_hochul", "stall") > u(s.branches, "ny_hochul", "amended"),
      src: ["https://www.cnbc.com/2026/02/19/new-york-driverless-rideshare-nyc-waymo.html"] },
    { id: "idg_stall", claim: "NYC driver unions fought robotaxis and claimed victory when the plan died",
      check: s => u(s.branches, "idg", "stall") > u(s.branches, "idg", "amended"),
      src: ["https://driversguild.org/idg-victory-in-ny-governor-pulls-robotaxi-proposal-from-budgetidg-warns-hochul-robotaxi-proposal-will-kill-jobs/"] },
    { id: "teamsters_stall", claim: "Teamsters fight robotaxi legalization and push human-operator mandates (DC, MA, TX)",
      check: s => u(s.branches, "teamsters", "stall") > u(s.branches, "teamsters", "amended"),
      src: ["https://teamster.org/2026/07/dc-teamsters-labor-coalition-demand-city-council-reject-anti-worker-waymo-bill/"] },
    { id: "atu_stall", claim: "ATU opposed NJDOT's Trenton AV transit project and wants AVs barred from transit",
      check: s => u(s.branches, "atu", "stall") > u(s.branches, "atu", "amended"),
      src: ["https://atu.org/media/press/2022/atu-nj-dots-autonomous-vehicle-trenton-project-poses-serious-public-safety-risks-and-wastes-precious-taxpayer-resources"] },
  ];

  function fit(m, opts = {}) {
    const s = g.solve(m, opts);
    const results = FACTS.map(f => ({ id: f.id, claim: f.claim, pass: !!f.check(s) }));
    const passed = results.filter(r => r.pass).length;
    return { passed, total: FACTS.length, results };
  }

  // Letter grade for a normalized utility in [-1, 1].
  const letter = x => (x >= 0.6 ? "A" : x >= 0.2 ? "B" : x > -0.2 ? "C" : x > -0.6 ? "D" : "F");

  const api = { FACTS, fit, letter };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.AVCalibrate = api;
})(typeof window !== "undefined" ? window : globalThis);
