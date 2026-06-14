import type { ReactNode } from "react";

const TOKEN_REGEX =
  /"(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(?:\s*:)?|\btrue\b|\bfalse\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;

/**
 * Tokenize a `JSON.stringify(data, null, 2)` string into highlighted spans.
 * Regex-based on purpose — avoids a parser/AST dependency for what is
 * ultimately a read-only syntax highlight inside a `<pre>`.
 */
export function highlightJson(json: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = TOKEN_REGEX.exec(json)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(json.slice(lastIndex, match.index));
    }

    const token = match[0];
    let className: string;
    if (token.startsWith('"')) {
      className = token.endsWith(":") ? "json-key" : "json-string";
    } else if (token === "true" || token === "false") {
      className = "json-boolean";
    } else if (token === "null") {
      className = "json-null";
    } else {
      className = "json-number";
    }

    nodes.push(
      <span key={key++} className={className}>
        {token}
      </span>
    );
    lastIndex = TOKEN_REGEX.lastIndex;
  }

  if (lastIndex < json.length) {
    nodes.push(json.slice(lastIndex));
  }

  return nodes;
}
