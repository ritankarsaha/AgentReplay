import { ArrowRight, OctagonX } from "lucide-react";
import Link from "next/link";

import { RelativeTime } from "@/components/relative-time";
import type { SpanOut } from "@/lib/api";
import type { IncidentOut } from "@/lib/control-plane";

export function HaltedBanner({ spans, incident }: { spans: SpanOut[]; incident: IncidentOut | null }) {
  const alert = spans.find((s) => s.type === "alert");
  const input = (alert?.input ?? {}) as Record<string, unknown>;
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-lg border border-status-failure/50 bg-status-failure/10 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2 text-sm font-semibold text-status-failure">
        <OctagonX className="size-4" />
        This run was halted by the scope guard
        {alert && <span className="font-normal text-status-failure/80"><RelativeTime iso={alert.started_at} /></span>}
      </div>
      {alert && (
        <p className="text-sm text-foreground">
          The agent tried to call <code className="font-mono">{String(input.tool)}</code>, which broke the rule{" "}
          <code className="font-mono">{String(input.rule)}</code>: {String(input.reason)}. The call never ran and every
          later call in this run was denied.
        </p>
      )}
      {incident && (
        <Link href={`/incidents/${incident.id}`} className="inline-flex w-fit items-center gap-1 text-sm font-medium text-status-failure underline-offset-4 hover:underline">
          Open the incident
          <ArrowRight className="size-3.5" />
        </Link>
      )}
    </div>
  );
}
