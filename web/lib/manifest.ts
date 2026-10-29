import { createHash, createPublicKey, verify } from "node:crypto";

import type { ManifestPayload } from "./control-plane";

const SPKI_ED25519_PREFIX = Buffer.from("302a300506032b6570032100", "hex");

function fromB64Url(value: string): Buffer {
  return Buffer.from(value.replace(/-/g, "+").replace(/_/g, "/"), "base64");
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function agentIdFor(publicKey: string): string {
  return "agt_" + createHash("sha256").update(fromB64Url(publicKey)).digest("hex").slice(0, 16);
}

/** Independent check of the manifest signature, matching controlplane/govern/identity.py. */
export function verifyManifest(manifest: ManifestPayload, publicKey: string): boolean {
  try {
    const raw = fromB64Url(publicKey);
    if (raw.length !== 32 || manifest.agent_id !== agentIdFor(publicKey)) return false;
    const { signature, ...payload } = manifest;
    const key = createPublicKey({ key: Buffer.concat([SPKI_ED25519_PREFIX, raw]), format: "der", type: "spki" });
    return verify(null, Buffer.from(canonical({ ...payload, allowed_tools: [...payload.allowed_tools].sort() })), key, fromB64Url(signature));
  } catch {
    return false;
  }
}
