import { Scale } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tag } from "@/components/ui/tag";
import { getModelRuns } from "@/lib/control-plane";
import { aggregate } from "@/lib/scoreboard";
import { requireProjectScope } from "@/lib/viewer";

const TASK_LABEL: Record<string, string> = { flight_selection: "Pick a flight from a stale document and a sponsored listing" };

export default async function ScoreboardPage() {
  const scope = await requireProjectScope();
  const rows = aggregate(await getModelRuns(scope));

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <Scale className="size-4 text-muted-foreground" />
          Model scoreboard
        </h1>
        <p className="text-sm text-muted-foreground">
          The same recorded decision, replayed against several models. Who would repeat the mistake?
        </p>
      </div>
      {rows.length === 0 ? (
        <EmptyState
          title="No model runs yet"
          description="Run the scoreboard fan-out on an incident (controlplane.learn.scoreboard) to fill this page."
        />
      ) : (
        <>
          <Card>
            <CardContent className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Task</TableHead>
                    <TableHead>Model</TableHead>
                    <TableHead>Repeats the mistake?</TableHead>
                    <TableHead>Correct</TableHead>
                    <TableHead>Errors</TableHead>
                    <TableHead className="text-right">Cost</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={`${row.taskClass}-${row.model}`}>
                      <TableCell className="max-w-64 whitespace-normal text-xs text-muted-foreground">
                        {TASK_LABEL[row.taskClass] ?? row.taskClass}
                      </TableCell>
                      <TableCell className="font-mono text-sm">{row.model}</TableCell>
                      <TableCell>
                        {row.repeatsMistake === null ? (
                          <Tag tone="muted">no usable result</Tag>
                        ) : row.repeatsMistake ? (
                          <Tag tone="bad">YES ({row.repeats} of {row.trials} trials)</Tag>
                        ) : (
                          <Tag tone="ok">no</Tag>
                        )}
                      </TableCell>
                      <TableCell className="font-mono text-sm">
                        {row.correct}/{row.trials}
                      </TableCell>
                      <TableCell className={row.errors ? "font-mono text-sm text-status-divergence" : "font-mono text-sm text-muted-foreground"}>
                        {row.errors}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm text-muted-foreground">
                        {row.costUsd != null ? `$${row.costUsd.toFixed(4)}` : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <p className="text-xs text-muted-foreground">
            Each row is measured output of real API calls (3 trials per model). The model only picks a flight; whether
            that pick repeats the mistake is judged by deterministic code against the live listing. Empty or unusable
            replies are counted as errors, not dropped. Cost is shown only for models with a known price.
          </p>
        </>
      )}
    </main>
  );
}
