import { Fingerprint } from "lucide-react";

import { CopyButton } from "@/components/copy-button";
import { RelativeTime } from "@/components/relative-time";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tag } from "@/components/ui/tag";
import type { AgentOut } from "@/lib/control-plane";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="flex items-center gap-1.5 truncate font-mono text-sm text-foreground">{children}</span>
    </div>
  );
}

export function AgentIdentityCard({ agent }: { agent: AgentOut }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Fingerprint className="size-4 text-muted-foreground" />
          Identity
          <Tag tone={agent.status === "active" ? "ok" : "bad"}>{agent.status}</Tag>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Name">{agent.name}</Field>
        <Field label="Agent id (derived from the public key)">
          {agent.id}
          <CopyButton value={agent.id} label="Copy agent id" />
        </Field>
        <Field label="Ed25519 public key">
          <span className="truncate">{agent.public_key}</span>
          <CopyButton value={agent.public_key} label="Copy public key" />
        </Field>
        <Field label="Registered">{agent.created_at ? <RelativeTime iso={agent.created_at} /> : "—"}</Field>
      </CardContent>
    </Card>
  );
}
