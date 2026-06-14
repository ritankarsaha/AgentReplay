/** Span duration as a compact string: "123ms" or "1.2s". */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Time-of-day with milliseconds, e.g. "14:32:01.123" — dense, for the timeline. */
export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number, len = 2) => n.toString().padStart(len, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

/** Full absolute timestamp, for hover titles. */
export function formatAbsolute(iso: string): string {
  return new Date(iso).toLocaleString();
}

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 60 * 60 * 24 * 365],
  ["month", 60 * 60 * 24 * 30],
  ["day", 60 * 60 * 24],
  ["hour", 60 * 60],
  ["minute", 60],
  ["second", 1],
];

const relativeFormatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "3m ago" / "2h ago" style relative time. */
export function formatRelativeTime(iso: string): string {
  const diffSeconds = (new Date(iso).getTime() - Date.now()) / 1000;

  for (const [unit, secondsInUnit] of RELATIVE_UNITS) {
    if (Math.abs(diffSeconds) >= secondsInUnit || unit === "second") {
      const value = Math.round(diffSeconds / secondsInUnit);
      return relativeFormatter.format(value, unit);
    }
  }
  return relativeFormatter.format(0, "second");
}
