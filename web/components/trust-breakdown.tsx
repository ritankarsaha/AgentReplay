import type { TrustComponents } from "@/lib/control-plane";
import { COMPONENT_WEIGHTS } from "@/lib/trust";

export function TrustBreakdown({ components }: { components: TrustComponents }) {
  return (
    <div className="flex flex-col gap-3">
      {COMPONENT_WEIGHTS.map(({ key, label, weight, invert }) => {
        const raw = components[key];
        const good = invert ? 1 - raw : raw;
        return (
          <div key={key} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-foreground">{label}</span>
              <span className="font-mono text-muted-foreground">
                {raw.toFixed(2)} · weight {Math.round(weight * 100)}% · +{(weight * good * 550).toFixed(0)} pts
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-status-ok" style={{ width: `${Math.max(good, 0) * 100}%` }} />
            </div>
          </div>
        );
      })}
      <p className="text-xs text-muted-foreground">
        score = 300 + 550 × composite ({components.composite.toFixed(3)}). Computed by a deterministic formula from
        recorded runs, scope violations and regression results.
      </p>
    </div>
  );
}
