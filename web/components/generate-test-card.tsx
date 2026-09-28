"use client";

import { useState } from "react";
import { FlaskConical, Loader2, ScanSearch } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeFile } from "@/components/code-file";
import type { GenerateTestResult } from "@/lib/api";

type Status = "idle" | "loading" | "error" | "success";

export function GenerateTestCard({ runId }: { runId: string }) {
  const [entrypoint, setEntrypoint] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateTestResult | null>(null);

  async function handleGenerate() {
    const trimmed = entrypoint.trim();
    if (!trimmed || status === "loading") return;

    setStatus("loading");
    setErrorMessage(null);

    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/generate-test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entrypoint: trimmed }),
      });
      const body = await res.json().catch(() => null);

      if (!res.ok) {
        throw new Error((body && body.detail) || `request failed (${res.status})`);
      }

      setResult(body as GenerateTestResult);
      setStatus("success");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "unknown error");
      setStatus("error");
    }
  }

  const spec = result?.assertion_spec;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FlaskConical className="size-4 text-muted-foreground" />
          Generate Test
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Turns this recorded run into a runnable pytest file: every recorded tool call is mocked
          from the trace, the agent&apos;s entrypoint is replayed with the original input, and the
          result is checked against an assertion spec — generated automatically below if this run
          doesn&apos;t have one yet.
        </p>

        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={entrypoint}
              onChange={(event) => setEntrypoint(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") handleGenerate();
              }}
              placeholder="examples.langgraph_demo:main"
              disabled={status === "loading"}
              className="h-8 min-w-0 flex-1 rounded-lg border border-border bg-background px-2.5 font-mono text-sm text-foreground outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 sm:min-w-64"
            />
            <Button onClick={handleGenerate} disabled={status === "loading" || !entrypoint.trim()}>
              {status === "loading" ? (
                <Loader2 data-icon="inline-start" className="animate-spin" />
              ) : (
                <FlaskConical data-icon="inline-start" />
              )}
              Generate Test
            </Button>
          </div>
          <span className="text-xs text-muted-foreground">
            The Python import path to the function that ran this agent, as{" "}
            <code className="font-mono">module.path:function_name</code> — e.g.{" "}
            <code className="font-mono">examples.langgraph_demo:main</code>. Must be importable
            from wherever <code className="font-mono">pytest</code> will run.
          </span>
        </div>

        {status === "error" && errorMessage && (
          <div className="rounded-sm border border-status-failure/40 bg-status-failure/10 px-2.5 py-1.5 font-mono text-xs text-status-failure">
            {errorMessage}
          </div>
        )}

        {status === "success" && result && (
          <div className="flex flex-col gap-2">
            {spec && (
              <div className="flex flex-col gap-1.5 rounded-md border border-border bg-muted/30 px-3 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  {spec.must_call_tools.map((tool) => (
                    <Badge key={`must-call-${tool}`} variant="outline" className="font-mono">
                      must call: {tool}
                    </Badge>
                  ))}
                  {spec.must_not_call_tools.map((tool) => (
                    <Badge key={`must-not-call-${tool}`} variant="outline" className="font-mono">
                      must not call: {tool}
                    </Badge>
                  ))}
                  {spec.max_steps !== null && (
                    <Badge variant="outline" className="font-mono">
                      max {spec.max_steps} step{spec.max_steps === 1 ? "" : "s"}
                    </Badge>
                  )}
                </div>
                {spec.rationale && <span className="text-sm text-foreground">{spec.rationale}</span>}
              </div>
            )}

            {spec?.semantic_rubric && (
              <div className="flex flex-col gap-1 rounded-md border border-border bg-muted/30 px-3 py-2">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <ScanSearch className="size-3.5" />
                  Content check — judged by an LLM each time the test runs, not pre-computed
                </div>
                <span className="text-sm text-foreground">{spec.semantic_rubric}</span>
              </div>
            )}

            <CodeFile filename={result.fixture_filename} source={result.fixture_source} />
            <CodeFile filename={result.test_filename} source={result.test_source} defaultOpen />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
