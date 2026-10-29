import { Card, CardContent } from "@/components/ui/card";
import { Tag } from "@/components/ui/tag";

const ROWS = [
  {
    tone: "ok" as const,
    label: "Real",
    items: "Trace capture and replay, signed scope enforcement and the halt, trust-score formula, premium formula, Muse Spark calls, measured benchmark numbers.",
  },
  {
    tone: "sim" as const,
    label: "Sandboxed",
    items: "The airline site and the seller, access-token connectors, payment rails.",
  },
  {
    tone: "warn" as const,
    label: "Simulated",
    items: "The dispute and insurance filings, SMS telephony.",
  },
];

export function RealityLegend() {
  return (
    <Card size="sm">
      <CardContent className="flex flex-col gap-2">
        <span className="text-xs font-medium text-muted-foreground">What is real in this demo</span>
        {ROWS.map((row) => (
          <div key={row.label} className="flex items-start gap-3 text-xs">
            <Tag tone={row.tone} className="mt-0.5 w-24 justify-center">
              {row.label}
            </Tag>
            <span className="text-muted-foreground">{row.items}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
