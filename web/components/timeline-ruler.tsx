import { formatDuration } from "@/lib/format";
import type { TimeBounds } from "@/lib/span-timing";

const TICKS = [0, 0.25, 0.5, 0.75, 1];

/**
 * First row of the span-timeline grid: a "Span" label cell + a row of
 * duration ticks (0% / 25% / 50% / 75% / 100% of the run's total span)
 * aligned over the waterfall column below.
 */
export function TimelineRuler({ bounds }: { bounds: TimeBounds }) {
  return (
    <div className="contents">
      <div className="flex items-center border-b border-border bg-muted/30 px-3 py-1.5 text-xs font-medium text-muted-foreground">
        Span
      </div>
      <div className="timeline-ruler bg-muted/30">
        {TICKS.map((tick) => (
          <span
            key={tick}
            className="timeline-ruler__tick"
            style={{
              left: `${tick * 100}%`,
              transform:
                tick === 0
                  ? "translateY(-50%)"
                  : tick === 1
                    ? "translateY(-50%) translateX(-100%)"
                    : "translateY(-50%) translateX(-50%)",
            }}
          >
            {formatDuration(bounds.totalMs * tick)}
          </span>
        ))}
      </div>
    </div>
  );
}
