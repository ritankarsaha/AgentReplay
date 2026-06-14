import { CheckCircle2, GitCompare, Layers, XCircle } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { RunOut, RunStatus } from "@/lib/api";

const STATUS_META: Record<RunStatus, { label: string; icon: typeof CheckCircle2; colorVar: string }> = {
  ok: { label: "Ok", icon: CheckCircle2, colorVar: "var(--status-ok)" },
  failure: { label: "Failures", icon: XCircle, colorVar: "var(--status-failure)" },
  divergence: { label: "Divergence", icon: GitCompare, colorVar: "var(--status-divergence)" },
};

export function RunsOverview({ runs }: { runs: RunOut[] }) {
  const counts: Record<RunStatus, number> = { ok: 0, failure: 0, divergence: 0 };
  for (const run of runs) counts[run.status] += 1;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Card size="sm">
        <CardContent className="flex flex-col gap-1">
          <span className="flex items-center gap-1.5 font-mono text-2xl font-semibold text-foreground">
            <Layers className="size-4 text-muted-foreground" />
            {runs.length}
          </span>
          <span className="text-xs text-muted-foreground">Total runs</span>
        </CardContent>
      </Card>
      {(Object.keys(STATUS_META) as RunStatus[]).map((status) => {
        const meta = STATUS_META[status];
        const Icon = meta.icon;
        return (
          <Card key={status} size="sm">
            <CardContent className="flex flex-col gap-1">
              <span
                className="flex items-center gap-1.5 font-mono text-2xl font-semibold"
                style={{ color: meta.colorVar }}
              >
                <Icon className="size-4" />
                {counts[status]}
              </span>
              <span className="text-xs text-muted-foreground">{meta.label}</span>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
