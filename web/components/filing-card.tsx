import { FileWarning, ShieldCheck } from "lucide-react";

import { CopyButton } from "@/components/copy-button";
import { SimulatedBadge } from "@/components/simulated-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tag } from "@/components/ui/tag";
import type { FilingOut } from "@/lib/control-plane";
import { formatInr } from "@/lib/trust";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="truncate font-mono text-sm text-foreground">{children}</span>
    </div>
  );
}

export function FilingCard({ filing }: { filing: FilingOut }) {
  const p = filing.packet;
  const isClaim = p.type === "claim";
  const Icon = isClaim ? ShieldCheck : FileWarning;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Icon className="size-4 text-muted-foreground" />
          {isClaim ? "Insurance claim" : "Payment dispute"}
          <SimulatedBadge label="simulated filing" />
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm text-foreground">{p.narrative ?? p.dispute_narrative}</p>

        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Field label="Merchant">{p.transaction.merchant}</Field>
          <Field label="Amount">{formatInr(p.transaction.amount_inr)}</Field>
          <Field label="Booking">{p.transaction.booking_ref}</Field>
          <Field label="Flight">{p.transaction.flight}</Field>
          <Field label="Expected">{p.discrepancy.expected}</Field>
          <Field label="Actual">{p.discrepancy.actual}</Field>
          {p.requested_remedy && <Field label="Requested remedy">{p.requested_remedy}</Field>}
          <Field label="Principal's request">{p.principal_intent.text}</Field>
        </div>

        {isClaim && p.policy && p.loss && (
          <div className="grid grid-cols-2 gap-4 rounded-md border border-border bg-muted/30 px-3 py-3 sm:grid-cols-4">
            <Field label="Trust band">
              {p.policy.trust_band} {p.policy.trust_score != null && `(${p.policy.trust_score})`}
            </Field>
            <Field label="Premium">{formatInr(p.policy.premium_inr)}</Field>
            <Field label="Coverage limit">{formatInr(p.policy.coverage_limit)}</Field>
            <Field label="Deductible">{formatInr(p.policy.deductible)}</Field>
            <Field label="Payable">{formatInr(p.loss.payable_inr)}</Field>
            <div className="col-span-2 text-xs text-muted-foreground sm:col-span-3">
              premium = {formatInr(p.policy.coverage_limit)} × {p.policy.base_rate} × band multiplier {p.policy.band_multiplier}.
              A lower trust band pays more.
            </div>
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-muted-foreground">Evidence</span>
          <div className="flex flex-wrap gap-1.5">
            {p.evidence.map((e) => (
              <Tag key={`${e.role}-${e.span_id}`} tone="info" title={`sha256 ${e.hash}`} className="font-mono">
                {e.role} · {e.span_id.slice(0, 8)}
              </Tag>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1 font-mono">
            trace {filing.trace_hash.slice(0, 16)}…
            <CopyButton value={filing.trace_hash} label="Copy trace hash" />
          </span>
          {p.scope_manifest_hash && <span className="font-mono">manifest {p.scope_manifest_hash.slice(0, 16)}…</span>}
          <span>Redacted before export. Nothing here is sent to any real payment network or insurer.</span>
        </div>

        <details className="rounded-md border border-border">
          <summary className="cursor-pointer px-3 py-2 text-xs text-muted-foreground">Timeline ({p.timeline.length} events)</summary>
          <ol className="flex flex-col gap-1 border-t border-border px-3 py-2">
            {p.timeline.map((t) => (
              <li key={t.span_id} className="flex gap-3 text-xs">
                <span className="w-24 shrink-0 font-mono text-muted-foreground">{t.type}</span>
                <span className="text-foreground">{t.summary}</span>
              </li>
            ))}
          </ol>
        </details>
      </CardContent>
    </Card>
  );
}
