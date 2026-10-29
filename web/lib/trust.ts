export const TRUST_MIN = 300;
export const TRUST_MAX = 850;

export const BANDS = [
  { id: "restricted", label: "Restricted", min: 300, color: "var(--status-failure)", cap: "human approval" },
  { id: "probation", label: "Probation", min: 500, color: "var(--status-divergence)", cap: "₹2,000" },
  { id: "standard", label: "Standard", min: 600, color: "var(--span-tool)", cap: "₹6,000" },
  { id: "trusted", label: "Trusted", min: 700, color: "var(--status-ok)", cap: "₹15,000" },
] as const;

export function bandColor(band: string): string {
  return BANDS.find((b) => b.id === band)?.color ?? "var(--muted-foreground)";
}

export const COMPONENT_WEIGHTS = [
  { key: "recent_failure_rate", label: "Recent failure rate", weight: 0.35, invert: true },
  { key: "regression_pass_rate", label: "Regression pass rate", weight: 0.3, invert: false },
  { key: "scope_violation_penalty", label: "Scope-violation penalty", weight: 0.25, invert: true },
  { key: "history_factor", label: "Track record", weight: 0.1, invert: false },
] as const;

export function formatInr(value: number | null | undefined): string {
  return value == null ? "—" : `₹${Number(value).toLocaleString("en-IN")}`;
}
