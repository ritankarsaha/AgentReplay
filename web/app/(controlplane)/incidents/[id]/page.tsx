import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { IncidentView } from "@/components/incident-view";
import { RelativeTime } from "@/components/relative-time";
import { ShareControls } from "@/components/share-controls";
import { Tag } from "@/components/ui/tag";
import {
  getCaseForIncident,
  getCaseResults,
  getFilings,
  getGeneratedTest,
  getIncident,
  type CaseSummary,
} from "@/lib/control-plane";
import { requireProjectScope } from "@/lib/viewer";

export default async function IncidentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const scope = await requireProjectScope();
  const incident = await getIncident(scope, id);
  if (!incident) notFound();

  const [filings, found] = await Promise.all([getFilings(scope, id), getCaseForIncident(scope, id)]);
  let regressionCase: CaseSummary | null = null;
  let generated = null;
  if (found) {
    const [results, test] = await Promise.all([getCaseResults(scope, found.id), getGeneratedTest(scope, found.id)]);
    regressionCase = { ...found, results };
    generated = test;
  }

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <div>
        <Link href="/incidents" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3.5" />
          Incidents
        </Link>
      </div>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold">Incident {incident.id.slice(0, 8)}</h1>
          <Tag tone="bad">{incident.kind.replace("_", " ")}</Tag>
          <Tag tone={incident.status === "open" ? "warn" : "ok"}>{incident.status}</Tag>
          <Tag tone="muted">severity {incident.severity}</Tag>
          {incident.created_at && <span className="text-xs text-muted-foreground"><RelativeTime iso={incident.created_at} /></span>}
        </div>
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <Link href={`/runs/${incident.run_id}`} className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
            View the run trace
          </Link>
          {incident.agent_id && (
            <Link href={`/agents/${incident.agent_id}`} className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
              View the agent
            </Link>
          )}
        </div>
        <ShareControls incidentId={incident.id} shareToken={incident.share_token} open={incident.status === "open"} />
      </div>
      <IncidentView
        details={incident.details}
        filings={filings}
        regressionCase={regressionCase}
        generated={generated}
        blobBase="/api/blobs"
        runId={incident.run_id}
      />
    </main>
  );
}
