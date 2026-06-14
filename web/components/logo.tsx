import { cn } from "@/lib/utils";

/** Rounded-square mark: a 3-bar waveform using the span-type accent colors. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 28 28" className={cn("size-6 shrink-0", className)} aria-hidden="true">
      <rect width="28" height="28" rx="7" fill="var(--muted)" />
      <rect x="6" y="12" width="3.5" height="10" rx="1.5" fill="var(--span-node)" />
      <rect x="12.25" y="6" width="3.5" height="16" rx="1.5" fill="var(--span-llm)" />
      <rect x="18.5" y="10" width="3.5" height="12" rx="1.5" fill="var(--span-tool)" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-mono text-sm font-semibold tracking-tight", className)}>
      <span className="text-foreground">Agent</span>
      <span className="text-muted-foreground">Replay</span>
    </span>
  );
}
