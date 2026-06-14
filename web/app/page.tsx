import { Suspense } from "react";

import { EmptyState } from "@/components/empty-state";
import { RunsOverview } from "@/components/runs-overview";
import { RunsTable } from "@/components/runs-table";
import { RunsTableSkeleton } from "@/components/runs-table-skeleton";
import { getRuns } from "@/lib/api";

async function RunsTableSection() {
  const runs = await getRuns();

  if (runs.length === 0) {
    return (
      <EmptyState
        title="No runs yet"
        description="Run an instrumented agent (e.g. `python examples/resume_bot.py` from the repo root) — runs will appear here once spans are ingested."
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <RunsOverview runs={runs} />
      <RunsTable runs={runs} />
    </div>
  );
}

export default function RunsPage() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <div>
        <h1 className="text-lg font-semibold">Runs</h1>
        <p className="text-sm text-muted-foreground">Agent executions recorded by AgentReplay.</p>
      </div>
      <Suspense fallback={<RunsTableSkeleton />}>
        <RunsTableSection />
      </Suspense>
    </main>
  );
}
