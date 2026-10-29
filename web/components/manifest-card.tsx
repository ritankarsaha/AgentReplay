import { BadgeCheck, FileSignature, ShieldX } from "lucide-react";

import { CopyButton } from "@/components/copy-button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tag } from "@/components/ui/tag";
import type { ManifestOut } from "@/lib/control-plane";
import { formatAbsolute } from "@/lib/format";
import { verifyManifest } from "@/lib/manifest";
import { formatInr } from "@/lib/trust";

function Constraint({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-md border border-border bg-muted/30 px-3 py-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-sm text-foreground">{value}</span>
    </div>
  );
}

export function ManifestCard({ manifests, publicKey }: { manifests: ManifestOut[]; publicKey: string }) {
  const current = manifests.find((m) => !m.revoked_at) ?? null;
  if (!current) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileSignature className="size-4 text-muted-foreground" />
            Scope manifest
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {manifests.length === 0
            ? "No manifest published. With a guard installed this agent can call no tools."
            : "Every manifest has been revoked, so the agent is denied all tool calls."}
        </CardContent>
      </Card>
    );
  }

  const { manifest } = current;
  const verified = verifyManifest(manifest, publicKey);
  const c = manifest.constraints;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <FileSignature className="size-4 text-muted-foreground" />
          Scope manifest v{current.version}
          {verified ? (
            <Tag tone="ok" title="Verified here against the registered public key.">
              <BadgeCheck />
              signature verified
            </Tag>
          ) : (
            <Tag tone="bad">
              <ShieldX />
              signature invalid
            </Tag>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-muted-foreground">Allowed tools</span>
          <div className="flex flex-wrap gap-1.5">
            {manifest.allowed_tools.map((tool) => (
              <Tag key={tool} tone="info" className="font-mono">{tool}</Tag>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <Constraint label="Spend cap" value={formatInr(c.max_spend_inr)} />
          <Constraint label="Bookings per task" value={c.max_bookings_per_task != null ? String(c.max_bookings_per_task) : "—"} />
          <Constraint label="Geography" value={c.geography ?? "—"} />
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-muted-foreground">
          <span>issued {formatAbsolute(manifest.issued_at)}</span>
          <span>{manifest.expires_at ? `expires ${formatAbsolute(manifest.expires_at)}` : "no expiry"}</span>
          <span className="flex items-center gap-1 font-mono">
            sig {manifest.signature.slice(0, 16)}…
            <CopyButton value={manifest.signature} label="Copy signature" />
          </span>
        </div>
        {manifests.length > 1 && (
          <ul className="flex flex-col gap-1 border-t border-border pt-3 text-xs text-muted-foreground">
            {manifests.map((m) => (
              <li key={m.version} className="flex items-center gap-2">
                <span className="font-mono text-foreground">v{m.version}</span>
                {m.revoked_at ? <Tag tone="bad">revoked {formatAbsolute(m.revoked_at)}</Tag> : <Tag tone="ok">active</Tag>}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
