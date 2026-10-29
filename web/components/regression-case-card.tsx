import { FlaskConical } from "lucide-react";

import { CodeFile } from "@/components/code-file";
import { RelativeTime } from "@/components/relative-time";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tag } from "@/components/ui/tag";
import type { CaseSummary, GeneratedTest } from "@/lib/control-plane";

function verdictTone(verdict: string) {
  return verdict === "pass" ? "ok" : verdict === "fail" ? "bad" : "warn";
}

export function RegressionCaseCard({ regressionCase, generated }: { regressionCase: CaseSummary; generated?: GeneratedTest | null }) {
  const checks = regressionCase.assertion_spec?.output_checks ?? [];
  const results = [...regressionCase.results].reverse();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <FlaskConical className="size-4 text-muted-foreground" />
          Regression test
          <Tag tone="info">{regressionCase.priority}</Tag>
          <Tag tone={regressionCase.status === "active" ? "ok" : "muted"}>{regressionCase.status}</Tag>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm text-foreground">{regressionCase.title}</p>

        {checks.length > 0 && (
          <ul className="flex flex-col gap-1 text-sm text-foreground">
            {checks.map((c, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-muted-foreground">assert</span>
                <span>{c.description ?? `${c.path} ${c.op}`}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-muted-foreground">Runs (3 trials each, tools mocked from the recording)</span>
          {results.length === 0 && <p className="text-sm text-muted-foreground">Not run yet.</p>}
          <ol className="flex flex-col gap-1.5">
            {results.map((r, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
                <Tag tone={verdictTone(r.verdict)}>{r.verdict === "fail" ? "RED" : r.verdict === "pass" ? "GREEN" : r.verdict}</Tag>
                <span className="font-mono text-foreground">{r.passes}/{r.trials}</span>
                <span className="font-mono text-xs text-muted-foreground">{r.agent_version ?? "—"}</span>
                {r.judged_at && <span className="text-xs text-muted-foreground"><RelativeTime iso={r.judged_at} /></span>}
              </li>
            ))}
          </ol>
        </div>

        {generated && (
          <div className="flex flex-col gap-2">
            <span className="text-xs text-muted-foreground">
              Generated pytest file: commit it to your repo and the CI gate runs it on every PR.
            </span>
            <CodeFile filename={generated.test_filename} source={generated.test_source} />
            <CodeFile filename={generated.fixture_filename} source={generated.fixture_source} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
