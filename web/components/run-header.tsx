import { Card, CardContent } from "@/components/ui/card";
import { CopyButton } from "@/components/copy-button";
import { JsonViewer } from "@/components/json-viewer";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import { formatAbsolute } from "@/lib/format";
import type { RunDetailOut } from "@/lib/api";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-sm text-foreground">{children}</span>
    </div>
  );
}

export function RunHeader({ run }: { run: RunDetailOut }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={run.status} />
          <span className="flex items-center gap-1.5 font-mono text-sm text-foreground">
            {run.id}
            <CopyButton value={run.id} label="Copy run id" />
          </span>
          {run.status === "failure" && run.failure_class && (
            <span className="font-mono text-sm text-status-failure">
              {run.failure_class}
            </span>
          )}
        </div>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Field label="Agent version">{run.agent_version ?? "—"}</Field>
          <Field label="Framework">{run.framework ?? "—"}</Field>
          <Field label="Started">
            {formatAbsolute(run.started_at)} (<RelativeTime iso={run.started_at} />)
          </Field>
          <Field label="Last seen">{formatAbsolute(run.last_seen_at)}</Field>
        </div>

        {Object.keys(run.metadata).length > 0 && (
          <JsonViewer data={run.metadata} label="metadata" />
        )}
      </CardContent>
    </Card>
  );
}
