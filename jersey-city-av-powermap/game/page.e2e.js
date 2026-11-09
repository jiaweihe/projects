// Browser test for the built page: `node game/page.e2e.js` (uses the environment's preinstalled Playwright).
const { chromium } = require("playwright");
const path = require("path");
const assert = require("node:assert/strict");

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  p.on("pageerror", e => errors.push(e.message));
  await p.goto("file://" + path.join(__dirname, "index.html"));
  await p.waitForSelector("#tune-a");

  // Calibrated defaults: the page opens on the evidence-tuned model.
  const fitTxt = await p.textContent("#fit"), [got, of] = fitTxt.match(/(\d+)\/(\d+)/).slice(1).map(Number);
  assert.ok(of >= 10 && got === of, `calibrated page must reproduce every fact: ${fitTxt}`);
  const law0 = await p.textContent("#path .move b");
  assert.match(law0, /S1677/);

  // Tipping-point cards never show a vacuous threshold of 0.00.
  assert.doesNotMatch(await p.textContent("#flips"), /≥ 0\.00/);

  // Beli loop: pick the Legislature, answer "innovation" repeatedly, and the bill flips.
  await p.selectOption("#tune-actor", "zwicker");
  const w0 = await p.textContent("#tune-weights");
  for (let i = 0; i < 12; i++) {
    const a = await p.textContent("#tune-a"), bb = await p.textContent("#tune-b");
    const pick = /innovation/i.test(a) ? "#tune-a" : /innovation/i.test(bb) ? "#tune-b" : /risk|safety/i.test(a) ? "#tune-b" : "#tune-a";
    await p.click(pick);
  }
  assert.notEqual(await p.textContent("#tune-weights"), w0, "weights did not change");
  assert.match(await p.textContent("#tune-count"), /12/);
  assert.match(await p.textContent("#path .move b"), /amended/i, "equilibrium did not respond to answers");

  // Undo removes the last answer.
  await p.click("#tune-undo");
  assert.match(await p.textContent("#tune-count"), /11/);

  assert.deepEqual(errors, []);
  await b.close();
  console.log("e2e ok");
})().catch(e => { console.error("e2e FAIL:", e.message); process.exit(1); });
