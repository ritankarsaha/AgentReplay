import type { RunStatus, SpanType } from "./api";

/**
 * Single source of truth for the span-type / run-status color tokens
 * (defined in app/globals.css). Used by both badges and the timeline's
 * left-rail connectors so the two never drift apart.
 */
export const SPAN_TYPE_COLORS: Record<SpanType, string> = {
  node: "var(--span-node)",
  llm: "var(--span-llm)",
  tool: "var(--span-tool)",
  checkpoint: "var(--span-checkpoint)",
};

export const SPAN_TYPE_LABELS: Record<SpanType, string> = {
  node: "node",
  llm: "llm",
  tool: "tool",
  checkpoint: "checkpoint",
};

export const STATUS_COLORS: Record<RunStatus, string> = {
  ok: "var(--status-ok)",
  failure: "var(--status-failure)",
  divergence: "var(--status-divergence)",
};
