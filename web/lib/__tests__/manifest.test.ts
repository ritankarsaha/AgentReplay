import assert from "node:assert/strict";
import test from "node:test";

import { agentIdFor, verifyManifest } from "../manifest.ts";

// Same golden vector pinned in controlplane/tests/test_identity.py and ingest/tests/test_govern.py.
const PUBLIC_KEY = "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg";
const MANIFEST = {
  agent_id: "agt_56475aa75463474c",
  version: 1,
  allowed_tools: ["book_flight", "search_flights"],
  constraints: { max_spend_inr: 6000, max_bookings_per_task: 1, geography: "domestic" },
  issued_at: "2026-11-01T00:00:00Z",
  expires_at: "2036-10-29T00:00:00Z",
  signature: "rzVL3tI4gmRl_Tq9XKGmv59TzL1_WF6VAgHbRvI9z3kUkgx2Dnha4TqD_wosQBmjy2w6W-Q2EfVaWfDBoTanDw",
};

test("agent id is derived from the public key", () => {
  assert.equal(agentIdFor(PUBLIC_KEY), MANIFEST.agent_id);
});

test("the Python-signed golden manifest verifies", () => {
  assert.equal(verifyManifest(MANIFEST, PUBLIC_KEY), true);
});

test("allowed_tools order does not matter", () => {
  assert.equal(verifyManifest({ ...MANIFEST, allowed_tools: ["search_flights", "book_flight"] }, PUBLIC_KEY), true);
});

test("tampering breaks the signature", () => {
  assert.equal(verifyManifest({ ...MANIFEST, constraints: { ...MANIFEST.constraints, max_spend_inr: 60000 } }, PUBLIC_KEY), false);
  assert.equal(verifyManifest({ ...MANIFEST, allowed_tools: [...MANIFEST.allowed_tools, "wire_money"] }, PUBLIC_KEY), false);
  assert.equal(verifyManifest({ ...MANIFEST, version: 2 }, PUBLIC_KEY), false);
});

test("wrong key, wrong agent id and garbage input are rejected, never thrown", () => {
  assert.equal(verifyManifest(MANIFEST, "A".repeat(43)), false);
  assert.equal(verifyManifest({ ...MANIFEST, agent_id: "agt_other" }, PUBLIC_KEY), false);
  assert.equal(verifyManifest({ ...MANIFEST, signature: "not-a-signature" }, PUBLIC_KEY), false);
  assert.equal(verifyManifest(MANIFEST, "short"), false);
});
