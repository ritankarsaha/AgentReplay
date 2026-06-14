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
              {run.failure_class ?? "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
