import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { DiagnosisCard } from "@/components/diagnosis-card";
import { GenerateTestCard } from "@/components/generate-test-card";
import { HaltedBanner } from "@/components/halted-banner";
import { RunHeader } from "@/components/run-header";
import { RunStats } from "@/components/run-stats";
import { SpanTimeline } from "@/components/span-timeline";
import { getRun } from "@/lib/api";
import { getIncidents } from "@/lib/control-plane";
import { requireProjectScope } from "@/lib/viewer";
import { buildSpanTree } from "@/lib/span-tree";

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const scope = await requireProjectScope();
  const run = await getRun(scope, id);

  if (!run) notFound();

  const incident =
    run.status === "halted" ? ((await getIncidents(scope, { runId: run.id, limit: 1 }))[0] ?? null) : null;
  const tree = buildSpanTree(run.spans);
  const culpritSpanId = run.diagnosis?.culprit_span_id ?? run.root_span_id;

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <div>
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          Runs
        </Link>
      </div>
      <RunHeader run={run} />
      {run.status === "halted" && <HaltedBanner spans={run.spans} incident={incident} />}
      {run.status === "failure" && <DiagnosisCard run={run} />}
      {run.status === "failure" && <GenerateTestCard runId={run.id} />}
      <RunStats spans={run.spans} />
      <SpanTimeline nodes={tree} spans={run.spans} culpritSpanId={culpritSpanId} />
    </main>
  );
}
