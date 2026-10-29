import { TRUST_MAX, TRUST_MIN, bandColor, describeTrigger } from "@/lib/trust";
import type { TrustOut } from "@/lib/control-plane";
import { formatAbsolute } from "@/lib/format";
import { SimulatedBadge } from "@/components/simulated-badge";

const W = 520;
const H = 150;
const PAD = 24;
const PAD_LEFT = 40;

export function TrustHistory({ history }: { history: TrustOut[] }) {
  const points = [...history].reverse();
  if (points.length === 0) return <p className="text-sm text-muted-foreground">No trust score computed yet.</p>;

  const x = (i: number) => (points.length === 1 ? W / 2 : PAD_LEFT + (i * (W - PAD_LEFT - PAD)) / (points.length - 1));
  const y = (score: number) => H - PAD - ((score - TRUST_MIN) / (TRUST_MAX - TRUST_MIN)) * (H - 2 * PAD);
  const path = points.map((p, i) => `${i ? "L" : "M"} ${x(i)} ${y(p.score)}`).join(" ");

  return (
    <div className="flex flex-col gap-3">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Trust score history">
        {[500, 600, 700].map((t) => (
          <g key={t}>
            <line x1={PAD_LEFT} x2={W - PAD} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeDasharray="3 4" />
            <text x={2} y={y(t) + 3} fontSize={9} fill="var(--muted-foreground)">{t}</text>
          </g>
        ))}
        <path d={path} fill="none" stroke="var(--muted-foreground)" strokeWidth={1.5} />
        {points.map((p, i) => (
          <g key={i}>
            <circle cx={x(i)} cy={y(p.score)} r={4.5} fill={bandColor(p.band)}>
              <title>{`${p.score} (${p.band}) ${p.computed_at ? formatAbsolute(p.computed_at) : ""}`}</title>
            </circle>
            <text x={x(i)} y={y(p.score) - 9} fontSize={10} textAnchor="middle" fill="var(--foreground)">{p.score}</text>
          </g>
        ))}
      </svg>
      <ol className="flex flex-col gap-1 text-xs text-muted-foreground">
        {points.map((p, i) => (
          <li key={i} className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-foreground">{p.score}</span>
            <span className="capitalize" style={{ color: bandColor(p.band) }}>{p.band}</span>
            <span>{describeTrigger(p.trigger_run_id)}</span>
            {p.components.seeded && <SimulatedBadge label="seeded" />}
            {p.computed_at && <span>{formatAbsolute(p.computed_at)}</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}
