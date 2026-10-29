"use client";

import { Check, Link2, Link2Off } from "lucide-react";
import { useState, useTransition } from "react";

import { resolveIncidentAction, setIncidentShareAction } from "@/app/actions";
import { CopyButton } from "@/components/copy-button";
import { Button } from "@/components/ui/button";
import { useOrigin } from "@/lib/use-browser";

export function ShareControls({
  incidentId,
  shareToken,
  open,
}: {
  incidentId: string;
  shareToken: string | null;
  open: boolean;
}) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const run = (action: () => Promise<{ ok: boolean; message?: string }>) =>
    startTransition(async () => {
      const result = await action();
      setError(result.ok ? null : (result.message ?? "Something went wrong."));
    });

  const origin = useOrigin();
  const url = shareToken && origin ? `${origin}/share/${shareToken}` : null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {shareToken ? (
        <>
          <span className="flex items-center gap-1 rounded-md border border-border px-2 py-1 font-mono text-xs text-muted-foreground">
            {url ?? `/share/${shareToken.slice(0, 6)}…`}
            {url && <CopyButton value={url} label="Copy share link" />}
          </span>
          <Button size="sm" variant="outline" disabled={pending} onClick={() => run(() => setIncidentShareAction(incidentId, false))}>
            <Link2Off />
            Stop sharing
          </Button>
        </>
      ) : (
        <Button size="sm" variant="outline" disabled={pending} onClick={() => run(() => setIncidentShareAction(incidentId, true))}>
          <Link2 />
          Create read-only link
        </Button>
      )}
      {open && (
        <Button size="sm" variant="outline" disabled={pending} onClick={() => run(() => resolveIncidentAction(incidentId))}>
          <Check />
          Mark resolved
        </Button>
      )}
      {error && <span className="text-xs text-status-failure">{error}</span>}
    </div>
  );
}
