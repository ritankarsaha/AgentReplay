import { OctagonX } from "lucide-react";
import Link from "next/link";

import { RelativeTime } from "@/components/relative-time";
import { Tag } from "@/components/ui/tag";
import type { IncidentOut } from "@/lib/control-plane";

const KIND_LABEL: Record<string, string> = {
  scope_violation: "scope violation",
  spend_breach: "spend gate",
  failure: "failure",
};

export function IncidentList({ incidents }: { incidents: IncidentOut[] }) {
  if (incidents.length === 0) return <p className="text-sm text-muted-foreground">No incidents.</p>;
  return (
    <ul className="flex flex-col divide-y divide-border overflow-hidden rounded-lg border border-border bg-card">
      {incidents.map((incident) => {
        const cause = incident.details.causation?.map((c) => c.tag.replace("_", " ")) ?? [];
        return (
          <li key={incident.id}>
            <Link href={`/incidents/${incident.id}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 transition-colors hover:bg-muted/40">
              <OctagonX className="size-4 text-status-failure" />
              <span className="font-mono text-sm text-foreground">{incident.id.slice(0, 8)}</span>
              <Tag tone="bad">{KIND_LABEL[incident.kind] ?? incident.kind}</Tag>
              <Tag tone={incident.status === "open" ? "warn" : "ok"}>{incident.status}</Tag>
              {cause.map((c) => (
                <Tag key={c} tone="muted">{c}</Tag>
              ))}
              <span className="ml-auto text-xs text-muted-foreground">
                {incident.created_at ? <RelativeTime iso={incident.created_at} /> : null}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
