import { Bot } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { Card, CardContent } from "@/components/ui/card";
import { Tag } from "@/components/ui/tag";
import { getAgents, getTrustHistory } from "@/lib/control-plane";
import { bandColor } from "@/lib/trust";
import { requireProjectScope } from "@/lib/viewer";

export default async function AgentsPage() {
  const scope = await requireProjectScope();
  const agents = await getAgents(scope);
  const latest = await Promise.all(agents.map((a) => getTrustHistory(scope, a.id, 1).then((h) => h[0] ?? null)));

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <div>
        <h1 className="text-lg font-semibold">Agents</h1>
        <p className="text-sm text-muted-foreground">Registered identities, their signed scope and trust score.</p>
      </div>
      {agents.length === 0 ? (
        <EmptyState
          title="No agents registered"
          description="Register an agent's public key with POST /v1/agents, then publish a signed scope manifest."
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {agents.map((agent, i) => {
            const trust = latest[i];
            return (
              <Link key={agent.id} href={`/agents/${agent.id}`}>
                <Card className="transition-colors hover:ring-foreground/25">
                  <CardContent className="flex items-center gap-4">
                    <Bot className="size-5 text-muted-foreground" />
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="text-sm font-medium text-foreground">{agent.name}</span>
                      <span className="truncate font-mono text-xs text-muted-foreground">{agent.id}</span>
                    </div>
                    <Tag tone={agent.status === "active" ? "ok" : "bad"}>{agent.status}</Tag>
                    {trust && (
                      <span className="flex flex-col items-end">
                        <span className="font-mono text-xl font-semibold" style={{ color: bandColor(trust.band) }}>{trust.score}</span>
                        <span className="text-xs capitalize text-muted-foreground">{trust.band}</span>
                      </span>
                    )}
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </main>
  );
}
