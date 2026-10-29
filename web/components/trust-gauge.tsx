import { BANDS, TRUST_MAX, TRUST_MIN, bandColor, formatInr } from "@/lib/trust";

const R = 80;
const CX = 100;
const CY = 100;

function point(score: number, radius = R) {
  const t = (Math.min(Math.max(score, TRUST_MIN), TRUST_MAX) - TRUST_MIN) / (TRUST_MAX - TRUST_MIN);
  const angle = Math.PI * (1 - t);
  return { x: CX + radius * Math.cos(angle), y: CY - radius * Math.sin(angle) };
}

function arc(from: number, to: number) {
  const a = point(from);
  const b = point(to);
  return `M ${a.x} ${a.y} A ${R} ${R} 0 0 1 ${b.x} ${b.y}`;
}

export function TrustGauge({ score, band, capInr }: { score: number; band: string; capInr?: number }) {
  const needle = point(score, R - 14);
  const edges = [...BANDS.map((b) => b.min), TRUST_MAX];
  return (
    <div className="flex flex-col items-center gap-1">
      <svg viewBox="0 0 200 120" className="w-full max-w-64" role="img" aria-label={`Trust score ${score}, band ${band}`}>
        {BANDS.map((b, i) => (
          <path key={b.id} d={arc(edges[i], edges[i + 1])} stroke={b.color} strokeWidth={10} fill="none" opacity={b.id === band ? 1 : 0.28} />
        ))}
        <line x1={CX} y1={CY} x2={needle.x} y2={needle.y} stroke="var(--foreground)" strokeWidth={2.5} strokeLinecap="round" />
        <circle cx={CX} cy={CY} r={4} fill="var(--foreground)" />
        <text x={14} y={116} fontSize={9} fill="var(--muted-foreground)">{TRUST_MIN}</text>
        <text x={186} y={116} fontSize={9} fill="var(--muted-foreground)" textAnchor="end">{TRUST_MAX}</text>
      </svg>
      <span className="font-mono text-4xl font-semibold leading-none" style={{ color: bandColor(band) }}>{score}</span>
      <span className="text-sm font-medium capitalize" style={{ color: bandColor(band) }}>{band}</span>
      {capInr !== undefined && (
        <span className="text-xs text-muted-foreground">
          spend cap {capInr === 0 ? "— human approval required" : formatInr(capInr)}
        </span>
      )}
    </div>
  );
}
