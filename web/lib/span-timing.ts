import type { SpanOut } from "./api";

export interface TimeBounds {
  /** epoch ms of the earliest span start in the run. */
  startMs: number;
  /** total wall-clock span covered by the run, floored at 1 to avoid divide-by-zero. */
  totalMs: number;
}

/**
 * Compute the time window covered by a run's spans, for positioning bars on
 * the waterfall timeline. `startMs` is the earliest `started_at`; `totalMs`
 * is the distance to the latest `started_at + duration_ms`.
 */
export function computeTimeBounds(spans: SpanOut[]): TimeBounds {
  if (spans.length === 0) return { startMs: 0, totalMs: 1 };

  let minStart = Infinity;
  let maxEnd = -Infinity;
  for (const span of spans) {
    const start = new Date(span.started_at).getTime();
    const end = start + span.duration_ms;
    if (start < minStart) minStart = start;
    if (end > maxEnd) maxEnd = end;
  }

  return { startMs: minStart, totalMs: Math.max(maxEnd - minStart, 1) };
}

const MIN_WIDTH_PCT = 0.6;

/** Position (as percentages of `bounds.totalMs`) of a span's waterfall bar. */
export function timelinePosition(
  span: SpanOut,
  bounds: TimeBounds
): { offsetPct: number; widthPct: number } {
  const start = new Date(span.started_at).getTime();
  const offsetPct = Math.max(((start - bounds.startMs) / bounds.totalMs) * 100, 0);
  const rawWidthPct = (span.duration_ms / bounds.totalMs) * 100;
  const widthPct = Math.min(Math.max(rawWidthPct, MIN_WIDTH_PCT), 100 - offsetPct);

  return { offsetPct, widthPct: Math.max(widthPct, MIN_WIDTH_PCT) };
}
