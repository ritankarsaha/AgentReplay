import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { RunHeader } from "@/components/run-header";
import { RunStats } from "@/components/run-stats";
import { SpanTimeline } from "@/components/span-timeline";
import { getRun } from "@/lib/api";
import { buildSpanTree } from "@/lib/span-tree";

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const run = await getRun(id);

  if (!run) notFound();

  const tree = buildSpanTree(run.spans);

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
      <RunStats spans={run.spans} />
      <SpanTimeline nodes={tree} spans={run.spans} />
    </main>
  );
}
