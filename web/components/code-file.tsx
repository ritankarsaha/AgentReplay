"use client";

import { Download, FileCode2 } from "lucide-react";

import { CopyButton } from "@/components/copy-button";
import { cn } from "@/lib/utils";

function byteSize(text: string): string {
  const bytes = new TextEncoder().encode(text).length;
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function downloadTextFile(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/x-python" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function DownloadButton({ filename, source }: { filename: string; source: string }) {
  return (
    <button
      type="button"
      aria-label={`Download ${filename}`}
      title={`Download ${filename}`}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-sm p-0.5 text-muted-foreground transition-colors hover:text-foreground"
      )}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        downloadTextFile(filename, source);
      }}
    >
      <Download className="size-3" />
    </button>
  );
}

export function CodeFile({
  filename,
  source,
  defaultOpen = false,
}: {
  filename: string;
  source: string;
  defaultOpen?: boolean;
}) {
  return (
    <details className="code-viewer" open={defaultOpen}>
      <summary>
        <span>
          <FileCode2 className="size-3.5" />
          {filename} ({byteSize(source)})
        </span>
        <span className="code-viewer__actions">
          <CopyButton value={source} label={`Copy ${filename}`} />
          <DownloadButton filename={filename} source={source} />
        </span>
      </summary>
      <pre>
        <code>{source}</code>
      </pre>
    </details>
  );
}
