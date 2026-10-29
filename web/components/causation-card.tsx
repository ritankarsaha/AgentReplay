import { Link2, Megaphone, Route, Scale } from "lucide-react";
import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tag } from "@/components/ui/tag";
import type { CausationTag, DataFinding } from "@/lib/control-plane";

const TAGS = {
  intent_drift: { label: "Intent drift", icon: Route, hint: "The agent accepted something looser than what the user asked for." },
  sponsored: { label: "Sponsored influence", icon: Megaphone, hint: "A paid placement shaped the choice." },
  stale_data: { label: "Stale data", icon: Scale, hint: "The agent acted on out-of-date information." },
} as const;

export function CausationCard({
  causation,
  findings,
  runId,
}: {
  causation: CausationTag[];
  findings: DataFinding[];
  runId?: string;
}) {
  const spanLink = (id: string) =>
    runId ? (
      <Link key={id} href={`/runs/${runId}#span-${id}`} className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
        <Link2 className="size-3" />
        {id.slice(0, 8)}
      </Link>
    ) : (
      <span key={id} className="font-mono text-xs text-muted-foreground">{id.slice(0, 8)}</span>
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Why it happened</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {causation.length === 0 && <p className="text-sm text-muted-foreground">No contributing factor was identified in the trace.</p>}
        {causation.map((c) => {
          const meta = TAGS[c.tag];
          const Icon = meta.icon;
          return (
            <div key={c.tag} className="flex flex-col gap-1.5 rounded-md border border-border px-3 py-2.5">
              <div className="flex items-center gap-2">
                <Tag tone="warn" title={meta.hint}>
                  <Icon />
                  {meta.label}
                </Tag>
                <span className="text-xs text-muted-foreground">evidence</span>
                <span className="flex flex-wrap gap-2">{c.span_ids.map(spanLink)}</span>
              </div>
              <p className="text-sm text-foreground">{c.summary}</p>
            </div>
          );
        })}
        {findings.length > 0 && (
          <div className="flex flex-col gap-2 border-t border-border pt-3">
            <span className="text-xs font-medium text-muted-foreground">Data findings: clean this up first</span>
            {findings.map((f, i) => (
              <div key={i} className="flex flex-col gap-1 text-sm">
                <span className="flex flex-wrap items-center gap-2">
                  <Tag tone="warn">{f.kind === "stale_doc" ? "stale document" : "contradiction"}</Tag>
                  <span className="font-mono text-xs text-muted-foreground">
                    {f.kind === "stale_doc"
                      ? `${f.doc_id} · v${f.source_version}, live v${f.live_schedule_version}`
                      : `${f.fact}: document ${f.document_value}, live ${f.live_value}`}
                  </span>
                </span>
                <span className="text-muted-foreground">{f.action}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
