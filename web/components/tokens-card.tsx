import { KeyRound } from "lucide-react";

import { SimulatedBadge } from "@/components/simulated-badge";
import { RelativeTime } from "@/components/relative-time";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tag } from "@/components/ui/tag";
import type { TokenOut } from "@/lib/control-plane";

function tokenState(token: TokenOut): { label: string; tone: "ok" | "bad" | "warn" } {
  if (token.revoked_at) return { label: "revoked", tone: "bad" };
  if (token.expires_at && new Date(token.expires_at) <= new Date()) return { label: "expired", tone: "warn" };
  return { label: "active", tone: "ok" };
}

export function TokensCard({ tokens }: { tokens: TokenOut[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <KeyRound className="size-4 text-muted-foreground" />
          Access tokens
          <SimulatedBadge label="sandbox connector" />
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {tokens.length === 0 && <p className="text-sm text-muted-foreground">No tokens issued.</p>}
        {tokens.map((token) => {
          const state = tokenState(token);
          return (
            <div key={token.id} className="flex flex-wrap items-center gap-2 rounded-md border border-border px-3 py-2 text-sm">
              <span className="font-mono text-foreground">{token.connector}</span>
              {token.scopes.map((scope) => (
                <Tag key={scope} tone="info" className="font-mono">{scope}</Tag>
              ))}
              <Tag tone={state.tone}>{state.label}</Tag>
              <span className="ml-auto text-xs text-muted-foreground">
                {token.issued_at ? <RelativeTime iso={token.issued_at} /> : null}
              </span>
            </div>
          );
        })}
        <p className="text-xs text-muted-foreground">
          Only a hash of each token is stored. Issuance, expiry and revocation are real; the connectors are fakes.
        </p>
      </CardContent>
    </Card>
  );
}
