import assert from "node:assert/strict";
import test from "node:test";

import { bandColor, describeTrigger, formatInr } from "../trust.ts";

test("trust triggers are described in plain words", () => {
  assert.equal(describeTrigger(null), "recomputed");
  assert.equal(describeTrigger("seed:pre-demo"), "starting history");
  assert.equal(describeTrigger("regression:3f2a"), "regression test result");
  assert.equal(describeTrigger("577b9de7-7022-47ca-b555-fd0b9bbde71d"), "incident: run halted");
});

test("band colors and rupee formatting", () => {
  assert.equal(bandColor("trusted"), "var(--status-ok)");
  assert.equal(bandColor("nonsense"), "var(--muted-foreground)");
  assert.equal(formatInr(null), "—");
  assert.equal(formatInr(15000), "₹15,000");
});
