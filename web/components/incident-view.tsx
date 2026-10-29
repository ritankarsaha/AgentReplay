import { Film } from "lucide-react";

import { CausationCard } from "@/components/causation-card";
import { ClassificationCard } from "@/components/classification-card";
import { FilingCard } from "@/components/filing-card";
import { RealityLegend } from "@/components/reality-legend";
import { RegressionCaseCard } from "@/components/regression-case-card";
import { WalkthroughPlayer } from "@/components/walkthrough-player";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CaseSummary, FilingOut, GeneratedTest, IncidentDetails } from "@/lib/control-plane";

const FILING_ORDER = ["dispute", "claim"];

export function IncidentView({
  details,
  filings,
  regressionCase,
  generated,
  blobBase,
  runId,
}: {
  details: IncidentDetails;
  filings: FilingOut[];
  regressionCase: CaseSummary | null;
  generated?: GeneratedTest | null;
  blobBase: string;
  runId?: string;
}) {
  const walkthrough = details.walkthrough;
  return (
    <div className="flex flex-col gap-4">
      {walkthrough && walkthrough.beats.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Film className="size-4 text-muted-foreground" />
              Walkthrough
            </CardTitle>
          </CardHeader>
          <CardContent>
            <WalkthroughPlayer
              beats={walkthrough.beats}
              annotations={details.annotations ?? []}
              blobBase={blobBase}
              note={walkthrough.note}
            />
          </CardContent>
        </Card>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <CausationCard causation={details.causation ?? []} findings={details.data_findings ?? []} runId={runId} />
        <ClassificationCard classification={details.classification} notes={details.notes} />
      </div>
      {[...filings].sort((a, b) => FILING_ORDER.indexOf(a.type) - FILING_ORDER.indexOf(b.type)).map((filing) => (
        <FilingCard key={filing.type} filing={filing} />
      ))}
      {regressionCase && <RegressionCaseCard regressionCase={regressionCase} generated={generated} />}
      <RealityLegend />
    </div>
  );
}
