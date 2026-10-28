import { Radio } from "lucide-react";

import { CopyButton } from "@/components/copy-button";
import { INIT_SNIPPET } from "@/lib/snippets";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function Snippet({ label, code }: { label: string; code: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="font-mono text-[0.7rem] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <div className="relative rounded-md border border-border bg-background">
        <CopyButton value={code} label={`Copy ${label}`} className="absolute right-2 top-2" />
        <pre className="overflow-x-auto px-3 py-2.5 pr-8 font-mono text-xs leading-relaxed">
          <code>{code}</code>
        </pre>
      </div>
    </div>
  );
}

/** First-run guide shown while a project has no runs yet. */
export function Quickstart({
  projectName,
  keyPrefix,
}: {
  projectName: string;
  keyPrefix: string | null;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Radio className="size-4 text-muted-foreground" />
          Record your first run
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          Project <span className="font-mono text-foreground">{projectName}</span>
          {keyPrefix && (
            <>
              {" "}
              · key <span className="font-mono text-foreground">{keyPrefix}…</span>
            </>
          )}
          . This page updates automatically when your first run arrives.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Snippet label="1 · install" code="pip install agentreplay" />
        <Snippet label="2 · set your key" code="export AGENTREPLAY_API_KEY=ar_..." />
        <Snippet label="3 · instrument your agent" code={INIT_SNIPPET} />
        <Snippet label="Not seeing anything? Check your setup" code="agentreplay doctor" />
        <p className="text-xs text-muted-foreground">
          Lost your key? Keys are shown only once —{" "}
          <a href="/projects" className="underline underline-offset-2 hover:text-foreground">
            rotate it on the Projects page
          </a>
          .
        </p>
      </CardContent>
    </Card>
  );
}
