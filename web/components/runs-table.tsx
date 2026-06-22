import { AlertTriangle, Hourglass } from "lucide-react";
import Link from "next/link";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { RelativeTime } from "@/components/relative-time";
import { StatusBadge } from "@/components/status-badge";
import type { RunOut } from "@/lib/api";

/** Small inline cue (chunk 3.7) for the in-between classifier states — "done" just shows the failure_class text itself. */
function ClassificationHint({ run }: { run: RunOut }) {
  if (run.status !== "failure") return null;
  if (run.classification_status === "error") {
    return (
      <span title="Classifier error">
        <AlertTriangle className="size-3.5 text-status-failure" />
      </span>
    );
  }
  if (run.classification_status === "none") {
    return (
      <span title="Not classified yet">
        <Hourglass className="size-3.5 text-muted-foreground" />
      </span>
    );
  }
  return null;
}

export function RunsTable({ runs }: { runs: RunOut[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Status</TableHead>
          <TableHead>Run</TableHead>
          <TableHead>Agent version</TableHead>
          <TableHead>Framework</TableHead>
          <TableHead>Started</TableHead>
          <TableHead>Failure class</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.id} className="transition-colors hover:bg-muted/40">
            <TableCell>
              <StatusBadge status={run.status} />
            </TableCell>
            <TableCell>
              <Link
                href={`/runs/${run.id}`}
                className="font-mono text-sm text-foreground underline-offset-4 hover:underline"
                title={run.id}
              >
                {run.id.slice(0, 8)}
              </Link>
            </TableCell>
            <TableCell className="font-mono text-sm text-muted-foreground">
              {run.agent_version ?? "—"}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">
              {run.framework ?? "—"}
            </TableCell>
            <TableCell>
              <RelativeTime iso={run.started_at} />
            </TableCell>
            <TableCell
              className={
                run.status === "failure"
                  ? "font-mono text-sm text-status-failure"
                  : "font-mono text-sm text-muted-foreground"
              }
            >
              <span className="inline-flex items-center gap-1.5">
                <ClassificationHint run={run} />
                {run.failure_class ?? "—"}
              </span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
