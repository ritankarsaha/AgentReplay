import { AlertCircle, Clock, Layers } from "lucide-react";
import type { ReactNode } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { SpanTypeBadge } from "@/components/span-type-badge";
import type { SpanOut, SpanType } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { computeTimeBounds } from "@/lib/span-timing";

const SPAN_TYPES: SpanType[] = ["node", "llm", "tool", "checkpoint"];

function Stat({ icon, label, value }: { icon: ReactNode; label: string; value: ReactNode }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex size-8 items-center justify-center rounded-md bg-muted text-muted-foreground">
        {icon}
      </div>
      <div className="flex flex-col">
        <span className="font-mono text-sm font-medium text-foreground">{value}</span>
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
    </div>
  );
}

export function RunStats({ spans }: { spans: SpanOut[] }) {
  const bounds = computeTimeBounds(spans);
  const errorCount = spans.filter((span) => span.error !== null).length;
  const typeCounts = SPAN_TYPES.map((type) => ({
    type,
    count: spans.filter((span) => span.type === type).length,
  })).filter(({ count }) => count > 0);

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <Stat icon={<Clock className="size-4" />} label="Total duration" value={formatDuration(bounds.totalMs)} />
        <Stat icon={<Layers className="size-4" />} label="Spans" value={spans.length} />
        <Stat
          icon={<AlertCircle className="size-4" />}
          label="Errors"
          value={
            <span className={errorCount > 0 ? "text-status-failure" : undefined}>{errorCount}</span>
          }
        />
        <div className="flex flex-wrap items-center gap-2">
          {typeCounts.map(({ type, count }) => (
            <span key={type} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <SpanTypeBadge type={type} />
              {count}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
