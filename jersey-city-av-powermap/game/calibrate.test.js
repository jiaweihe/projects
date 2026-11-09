const test = require("node:test");
const assert = require("node:assert/strict");
const m = require("./model.json");
const c = require("./calibrate.js");

test("every observed fact is sourced and checkable", () => {
  assert.ok(c.FACTS.length >= 8);
  for (const f of c.FACTS) {
    assert.ok(f.id && f.claim && typeof f.check === "function", f.id);
    assert.ok(f.src.length && f.src.every(u => u.startsWith("https://")), f.id);
  }
});

test("fit() reports passed/total and per-fact results", () => {
  const r = c.fit(m);
  assert.equal(r.total, c.FACTS.length);
  assert.equal(r.results.length, r.total);
  assert.equal(r.passed, r.results.filter(x => x.pass).length);
});

test("baseline fit never drops below 6/8", () => {
  assert.ok(c.fit(m).passed >= 6, `fit ${c.fit(m).passed}`);
});

test("letter grades cover the normalized utility range", () => {
  assert.equal(c.letter(0.9), "A");
  assert.equal(c.letter(0.3), "B");
  assert.equal(c.letter(0), "C");
  assert.equal(c.letter(-0.3), "D");
  assert.equal(c.letter(-0.9), "F");
});
