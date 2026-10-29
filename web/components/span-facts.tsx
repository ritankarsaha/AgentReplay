import { Crosshair } from "lucide-react";

import { Tag } from "@/components/ui/tag";
import type { SpanOut } from "@/lib/api";
import { formatInr } from "@/lib/trust";

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj => (v && typeof v === "object" ? (v as Obj) : {});

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="font-mono text-xs text-foreground">{children}</span>
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">{children}</div>;
}

export function SpanFacts({ span }: { span: SpanOut }) {
  const out = obj(span.output);
  const inp = obj(span.input);

  switch (span.type) {
    case "policy":
    case "scope_violation": {
      const details = obj(out.details);
      const counters = obj(details.counters);
      return (
        <Grid>
          <Fact label="decision">{String(out.decision)} · {String(out.rule)}</Fact>
          <Fact label="reason">{String(out.reason)}</Fact>
          <Fact label="effective cap">{formatInr(details.effective_cap_inr as number)}</Fact>
          <Fact label="counters">{String(counters.bookings ?? 0)} booking(s) · {formatInr(counters.spent_inr as number)} spent</Fact>
        </Grid>
      );
    }
    case "alert":
      return (
        <Grid>
          <Fact label="kind">{String(inp.kind)}</Fact>
          <Fact label="rule">{String(inp.rule)}</Fact>
          <Fact label="blocked tool">{String(inp.tool)}</Fact>
          <Fact label="agent">{String(inp.agent_id ?? "—")}</Fact>
        </Grid>
      );
    case "message":
      return (
        <p className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm text-foreground">
          {String(out.body)}
        </p>
      );
    case "negotiation": {
      const conceded = (out.new_concessions as { lever: string; amount_inr: number }[] | undefined) ?? [];
      const rejected = Object.keys(obj(out.rejected_levers));
      return (
        <div className="flex flex-col gap-2">
          <Grid>
            <Fact label="round">{String(inp.round)} · buyer {String(inp.buyer)}</Fact>
            <Fact label="offered">{(inp.offered_levers as string[] | undefined)?.join(", ") || "—"}</Fact>
            <Fact label="price">{formatInr(out.list_price_inr as number)} → {formatInr(out.price_inr as number)}</Fact>
            <Fact label="seller says">{String(out.message)}</Fact>
          </Grid>
          <div className="flex flex-wrap gap-1.5">
            {conceded.map((c) => (
              <Tag key={c.lever} tone="ok">{c.lever} −{formatInr(c.amount_inr)}</Tag>
            ))}
            {rejected.map((r) => (
              <Tag key={r} tone="bad">refused {r}</Tag>
            ))}
          </div>
        </div>
      );
    }
    case "data_read":
      return (
        <Grid>
          <Fact label="document">{String(out.doc_id)}</Fact>
          <Fact label="updated">{String(out.doc_updated_at)}</Fact>
          <Fact label="document version">v{String(out.source_version)}</Fact>
          <Fact label="live schedule">v{String(out.live_schedule_version)}</Fact>
        </Grid>
      );
    case "decision": {
      const considered = (out.considered as Obj[] | undefined) ?? [];
      const chosen = obj(out.chosen);
      return (
        <div className="overflow-x-auto">
          <table className="w-full text-left font-mono text-xs">
            <thead className="text-muted-foreground">
              <tr>
                <th className="py-1 pr-4 font-normal">flight</th>
                <th className="pr-4 font-normal">price</th>
                <th className="pr-4 font-normal">listed</th>
                <th className="pr-4 font-normal">believed</th>
                <th className="pr-4 font-normal">sponsored</th>
                <th className="font-normal">fits</th>
              </tr>
            </thead>
            <tbody>
              {considered.map((row) => (
                <tr key={String(row.flight)} className={row.flight === chosen.flight ? "text-foreground" : "text-muted-foreground"}>
                  <td className="py-0.5 pr-4">
                    {row.flight === chosen.flight && <Crosshair className="mr-1 inline size-3 text-status-failure" />}
                    {String(row.flight)}
                  </td>
                  <td className="pr-4">{formatInr(row.price_inr as number)}</td>
                  <td className="pr-4">{String(row.listed_depart)}</td>
                  <td className={row.believed_depart !== row.listed_depart ? "pr-4 text-status-divergence" : "pr-4"}>{String(row.believed_depart)}</td>
                  <td className="pr-4">{row.sponsored ? "yes" : "no"}</td>
                  <td>{row.fits ? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="pt-1 text-[11px] text-muted-foreground">decided by: {String(out.chooser)}</p>
        </div>
      );
    }
    case "screenshot": {
      const image = obj(out.image);
      if (!image.sha256) return <p className="text-xs text-muted-foreground">No image captured (no browser available); HTML only.</p>;
      return (
        <a href={`/api/blobs/${String(image.sha256)}`} target="_blank" rel="noreferrer" className="block w-fit">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={`/api/blobs/${String(image.sha256)}`} alt="Booking confirmation page" className="max-h-48 rounded-md border border-border" />
        </a>
      );
    }
    default:
      return null;
  }
}

export const FACT_SPAN_TYPES = new Set(["policy", "scope_violation", "alert", "message", "negotiation", "data_read", "decision", "screenshot"]);
