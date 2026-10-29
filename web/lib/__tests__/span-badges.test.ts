import assert from "node:assert/strict";
import test from "node:test";

import type { SpanOut } from "../api.ts";
import { spanBadges } from "../span-badges.ts";

function span(type: string, output: unknown, name = "x"): SpanOut {
  return {
    id: "s1",
    run_id: "r",
    parent_id: null,
    type: type as SpanOut["type"],
    name,
    input: {},
    output,
    error: null,
    started_at: "2026-11-06T09:00:00Z",
    duration_ms: 1,
    fingerprint: null,
  };
}

const labels = (s: SpanOut) => spanBadges(s).map((b) => b.label);

test("policy spans show the decision and the rule that denied", () => {
  assert.deepEqual(labels(span("policy", { decision: "allow" })), ["allowed"]);
  assert.deepEqual(labels(span("policy", { decision: "deny", rule: "max_bookings" })), ["denied: max_bookings"]);
  assert.deepEqual(labels(span("scope_violation", { rule: "tool_not_allowed" })), ["blocked: tool_not_allowed"]);
  assert.deepEqual(labels(span("alert", {})), ["run halted"]);
});

test("a stale document is flagged only when its version is behind the live schedule", () => {
  assert.match(labels(span("data_read", { source_version: 5, live_schedule_version: 7 }))[0], /stale data \(v5, live v7\)/);
  assert.deepEqual(labels(span("data_read", { source_version: 7, live_schedule_version: 7 })), []);
});

test("sponsored listings are flagged on search results and on the decision", () => {
  assert.deepEqual(labels(span("tool", { results: [{ sponsored: false }, { sponsored: true }] }, "search_flights")), ["sponsored listing"]);
  assert.deepEqual(labels(span("tool", { results: [{ sponsored: false }] }, "search_flights")), []);
  const decision = labels(span("decision", { chosen: { sponsored: true, believed_depart: "07:30", listed_depart: "19:30" } }));
  assert.deepEqual(decision, ["sponsored pick", "believed 07:30, live 19:30"]);
});

test("simulated and sandboxed elements are always labeled", () => {
  assert.ok(labels(span("message", { direction: "inbound" })).includes("simulated SMS"));
  assert.ok(labels(span("negotiation", { status: "counter" })).includes("simulated seller"));
  assert.ok(labels(span("screenshot", {})).includes("sandbox airline"));
  assert.ok(labels(span("tool", { simulated: true }, "book_flight")).includes("sandbox airline"));
});

test("plain spans and non-object outputs produce no badges", () => {
  assert.deepEqual(labels(span("llm", { text: "hi" })), []);
  assert.deepEqual(labels(span("tool", "a string", "search_flights")), []);
  assert.deepEqual(labels(span("tool", null)), []);
});
