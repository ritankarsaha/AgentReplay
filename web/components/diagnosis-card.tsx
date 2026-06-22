import { AlertTriangle, ArrowRight, Hourglass, Stethoscope } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RelativeTime } from "@/components/relative-time";
import type { ClassificationStatus, RunDetailOut } from "@/lib/api";

const ASSERTION_TYPE_LABEL: Record<string, string> = {
  exact: "exact",
  structural: "structural",
  semantic: "semantic",
};

function ClassificationStatusBadge({ status }: { status: ClassificationStatus }) {
  if (status === "done") {
    return (
      <Badge variant="outline" className="border-status-ok/40 bg-status-ok/10 text-status-ok">
        classified
      </Badge>
    );
  }
  if (status === "error") {
    return (
      <Badge
        variant="outline"
        className="border-status-failure/40 bg-status-failure/10 text-status-failure"
      >
        <AlertTriangle data-icon="inline-start" />
        classifier error
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="border-border text-muted-foreground">
      <Hourglass data-icon="inline-start" />
      not classified
    </Badge>
  );
}

/**
 * Chunk 3.7 — surfaces chunk 3.6's classifier output. Only meaningful for a
 * failed run (`run.status === "failure"`); the page only renders this card
 * in that case (CLAUDE.md §6 demo script step 2: "failure auto-classified,
 * culprit span highlighted").
 */
export function DiagnosisCard({ run }: { run: RunDetailOut }) {
  const { classification_status: status, diagnosis } = run;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Stethoscope className="size-4 text-muted-foreground" />
            Diagnosis
          </CardTitle>
          <ClassificationStatusBadge status={status} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {status === "none" && (
          <p className="text-sm text-muted-foreground">
            Not classified yet — this may still be in progress, or no classifier backend is
            configured for this project (see <code>AGENTREPLAY_INGEST_ANTHROPIC_API_KEY</code> /{" "}
            <code>AGENTREPLAY_INGEST_NIM_API_KEY</code>).
          </p>
        )}

        {status === "error" && (
          <div className="rounded-sm border border-status-failure/40 bg-status-failure/10 px-2.5 py-1.5 font-mono text-xs text-status-failure">
            {diagnosis?.error ?? "Classification failed for an unknown reason."}
            {diagnosis?.backend && (
              <span className="ml-2 text-status-failure/70">(backend: {diagnosis.backend})</span>
            )}
          </div>
        )}

        {status === "done" && diagnosis && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-medium text-status-failure">
                {diagnosis.failure_class ?? run.failure_class}
              </span>
              {diagnosis.culprit_span_id && (
                <a
                  href={`#span-${diagnosis.culprit_span_id}`}
                  className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                >
                  jump to culprit span
                  <ArrowRight className="size-3" />
                </a>
              )}
            </div>

            {diagnosis.text && <p className="text-sm text-foreground">{diagnosis.text}</p>}

            {diagnosis.suggested_assertion && (
              <div className="flex flex-col gap-1 rounded-md border border-border bg-muted/30 px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Suggested assertion</span>
                  <Badge variant="outline" className="font-mono">
                    {ASSERTION_TYPE_LABEL[diagnosis.suggested_assertion.type] ??
                      diagnosis.suggested_assertion.type}
                  </Badge>
                </div>
                <span className="text-sm text-foreground">
                  {diagnosis.suggested_assertion.description}
                </span>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              {diagnosis.model && <span className="font-mono">{diagnosis.model}</span>}
              {diagnosis.backend && <span>({diagnosis.backend})</span>}
              {diagnosis.classified_at && (
                <span>
                  classified <RelativeTime iso={diagnosis.classified_at} />
                </span>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
