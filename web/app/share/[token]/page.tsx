import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { IncidentView } from "@/components/incident-view";
import { RelativeTime } from "@/components/relative-time";
import { Tag } from "@/components/ui/tag";
import { getPublicIncident } from "@/lib/control-plane";

export const metadata: Metadata = {
  title: "Shared incident — AgentReplay",
  robots: { index: false, follow: false },
};

export default async function SharedIncidentPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const shared = await getPublicIncident(token);
  if (!shared) notFound();

  const { incident, agent, run, filings, case: regressionCase } = shared;
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold">Incident {incident.id.slice(0, 8)}</h1>
          <Tag tone="bad">{incident.kind.replace("_", " ")}</Tag>
          <Tag tone={incident.status === "open" ? "warn" : "ok"}>{incident.status}</Tag>
          <Tag tone="muted">read-only</Tag>
          <span className="text-xs text-muted-foreground"><RelativeTime iso={incident.created_at} /></span>
        </div>
        <p className="text-sm text-muted-foreground">
          {agent ? `Agent ${agent.name}` : "An AI agent"} was halted{run ? ` during run ${run.id.slice(0, 8)}` : ""}. This page is a
          read-only snapshot shared by its owner.
        </p>
      </div>
      <IncidentView
        details={incident.details}
        filings={filings}
        regressionCase={regressionCase}
        blobBase={`/api/share/${token}/blobs`}
      />
    </main>
  );
}
