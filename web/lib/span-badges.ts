import type { SpanOut } from "./api";
import type { TagTone } from "@/components/ui/tag";

export interface SpanBadge {
  label: string;
  tone: TagTone;
  hint?: string;
}

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj => (v && typeof v === "object" ? (v as Obj) : {});

/** Inline cues derived only from recorded span payloads. */
export function spanBadges(span: SpanOut): SpanBadge[] {
  const out = obj(span.output);
  const badges: SpanBadge[] = [];

  switch (span.type) {
    case "policy": {
      const allowed = out.decision === "allow";
      badges.push({ label: allowed ? "allowed" : `denied: ${String(out.rule)}`, tone: allowed ? "ok" : "bad" });
      break;
    }
    case "scope_violation":
      badges.push({ label: `blocked: ${String(out.rule ?? "scope")}`, tone: "bad" });
      break;
    case "alert":
      badges.push({ label: "run halted", tone: "bad" });
      break;
    case "message":
      badges.push({ label: String(out.direction ?? "message"), tone: "muted" });
      badges.push({ label: "simulated SMS", tone: "sim", hint: "Produced by the SMS simulator, not a real telephony provider." });
      break;
    case "negotiation":
      badges.push({ label: String(out.status ?? "offer"), tone: out.status === "accepted" ? "ok" : "muted" });
      badges.push({ label: "simulated seller", tone: "sim", hint: "A rules engine in the demo world, not a real airline." });
      break;
    case "data_read": {
      const stale = Number(out.source_version) < Number(out.live_schedule_version);
      if (stale) {
        badges.push({
          label: `stale data (v${out.source_version}, live v${out.live_schedule_version})`,
          tone: "warn",
          hint: "The document is older than the live schedule version.",
        });
      }
      break;
    }
    case "decision": {
      const chosen = obj(out.chosen);
      if (chosen.sponsored) badges.push({ label: "sponsored pick", tone: "warn", hint: "The chosen flight was a sponsored listing." });
      if (chosen.believed_depart && chosen.believed_depart !== chosen.listed_depart) {
        badges.push({ label: `believed ${chosen.believed_depart}, live ${chosen.listed_depart}`, tone: "warn" });
      }
      break;
    }
    case "screenshot":
      badges.push({ label: "sandbox airline", tone: "sim" });
      break;
    case "tool": {
      const results = obj(out).results;
      if (Array.isArray(results) && results.some((r) => obj(r).sponsored)) {
        badges.push({ label: "sponsored listing", tone: "warn", hint: "Search results include a paid placement, flagged on the span." });
      }
      if (span.name === "book_flight" && out.simulated) badges.push({ label: "sandbox airline", tone: "sim" });
      break;
    }
  }
  return badges;
}
