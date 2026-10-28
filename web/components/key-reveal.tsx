"use client";

import { KeyRound, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { CopyButton } from "@/components/copy-button";
import { INIT_SNIPPET } from "@/lib/snippets";
import type { ProjectWithKey } from "@/lib/api";

/** One-time display of a freshly created/rotated API key. */
export function KeyReveal({ project, rotated }: { project: ProjectWithKey; rotated: boolean }) {
  const exportLine = `export AGENTREPLAY_API_KEY=${project.api_key}`;

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-status-ok/40 bg-status-ok/5 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <KeyRound className="size-4" />
        {rotated ? "New API key for" : "Project created:"} {project.name}
      </div>

      <div className="flex items-start gap-2 rounded-md border border-border bg-background px-3 py-2 font-mono text-xs">
        <code className="min-w-0 flex-1 break-all">{project.api_key}</code>
        <CopyButton value={project.api_key} label="Copy API key" />
      </div>

      <p className="flex items-start gap-1.5 text-xs text-status-failure">
        <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
        Copy it now — for security we only store a hash, so this key can&apos;t be shown again.
        {rotated && " The previous key has stopped working."}
      </p>

      <div className="flex flex-col gap-3">
        {[
          ["1 · install", "pip install agentreplay"],
          ["2 · set your key", exportLine],
          ["3 · instrument your agent", INIT_SNIPPET],
          ["4 · verify", "agentreplay doctor"],
        ].map(([label, code]) => (
          <div key={label} className="flex flex-col gap-1.5">
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
        ))}
      </div>

      <Link href="/" className="text-xs underline underline-offset-2 hover:text-foreground">
        Go to the dashboard and wait for your first run →
      </Link>
    </div>
  );
}
