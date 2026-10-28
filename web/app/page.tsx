import { Suspense } from "react";

import { AutoRefresh } from "@/components/auto-refresh";
import { Quickstart } from "@/components/quickstart";
import { RunsOverview } from "@/components/runs-overview";
import { RunsTable } from "@/components/runs-table";
import { RunsTableSkeleton } from "@/components/runs-table-skeleton";
import { getRuns } from "@/lib/api";
import { getViewerContext, requireProjectScope } from "@/lib/viewer";

async function RunsTableSection() {
  const scope = await requireProjectScope();
  const runs = await getRuns(scope);

  if (runs.length === 0) {
    const { active } = await getViewerContext();
    return (
      <div className="flex flex-col gap-4">
        <AutoRefresh intervalMs={5000} />
        <Quickstart projectName={active?.name ?? "your project"} keyPrefix={active?.api_key_prefix ?? null} />
      </div>
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
