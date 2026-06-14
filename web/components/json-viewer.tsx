import { CopyButton } from "@/components/copy-button";
import { highlightJson } from "@/lib/highlight-json";

function byteSize(text: string): string {
  const bytes = new TextEncoder().encode(text).length;
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function JsonViewer({
  data,
  label,
}: {
  data: unknown;
  label: string;
}) {
  if (data === null || data === undefined) return null;

  const text = JSON.stringify(data, null, 2);
  const isEmpty = text === "{}" || text === "[]";

  return (
    <details className="json-viewer">
      <summary>
        <span>
          {label} ({isEmpty ? "empty" : byteSize(text)})
        </span>
        {!isEmpty && <CopyButton value={text} label={`Copy ${label}`} />}
      </summary>
      {!isEmpty && (
        <pre>
          <code>{highlightJson(text)}</code>
        </pre>
      )}
    </details>
  );
}
