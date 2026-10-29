import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AgentIdentityCard } from "@/components/agent-identity-card";
import { IncidentList } from "@/components/incident-list";
import { ManifestCard } from "@/components/manifest-card";
import { TokensCard } from "@/components/tokens-card";
import { TrustBreakdown } from "@/components/trust-breakdown";
import { TrustGauge } from "@/components/trust-gauge";
import { TrustHistory } from "@/components/trust-history";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getAgent, getIncidents, getManifests, getTokens, getTrustHistory } from "@/lib/control-plane";
import { requireProjectScope } from "@/lib/viewer";

export default async function AgentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const scope = await requireProjectScope();
  const agent = await getAgent(scope, id);
  if (!agent) notFound();

  const [manifests, tokens, history, incidents] = await Promise.all([
    getManifests(scope, id),
    getTokens(scope, id),
    getTrustHistory(scope, id),
    getIncidents(scope, { agentId: id, limit: 10 }),
  ]);
  const latest = history[0] ?? null;

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <div>
        <Link href="/agents" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3.5" />
          Agents
        </Link>
      </div>
      <AgentIdentityCard agent={agent} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1.4fr]">
        <Card>
          <CardHeader>
            <CardTitle>Trust score</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            {latest ? (
              <>
                <TrustGauge score={latest.score} band={latest.band} capInr={latest.components.cap_inr} />
                <TrustBreakdown components={latest.components} />
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No trust score computed yet.</p>
            )}
          </CardContent>
        </Card>
        <div className="flex flex-col gap-4">
          <ManifestCard manifests={manifests} publicKey={agent.public_key} />
          <Card>
            <CardHeader>
              <CardTitle>Trust history</CardTitle>
            </CardHeader>
            <CardContent>
              <TrustHistory history={history} />
            </CardContent>
          </Card>
        </div>
      </div>
      <TokensCard tokens={tokens} />
      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">Incidents</h2>
        <IncidentList incidents={incidents} />
      </div>
    </main>
  );
}
