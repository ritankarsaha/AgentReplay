import { ErrorBanner } from "@/components/error-banner";
import { JsonViewer } from "@/components/json-viewer";
import { SpanTypeBadge } from "@/components/span-type-badge";
import { formatDuration, formatTimestamp } from "@/lib/format";
import { SPAN_TYPE_COLORS } from "@/lib/span-colors";
import { timelinePosition, type TimeBounds } from "@/lib/span-timing";
import type { SpanNode } from "@/lib/span-tree";

const MAX_INDENT_DEPTH = 6;
const INDENT_PX = 14;

function hasContent(data: unknown): boolean {
  if (data === null || data === undefined) return false;
  const text = JSON.stringify(data);
  return text !== "{}" && text !== "[]";
}

/**
 * One row of the flattened waterfall grid: a label cell (indent + badge +
 * name + duration) and a track cell containing a positioned waterfall bar.
 * If the span has an error or non-empty payloads, a full-width detail row
 * follows (via `grid-column: 1 / -1`).
 */
export function SpanRow({
  node,
  bounds,
  index,
}: {
  node: SpanNode;
  bounds: TimeBounds;
  index: number;
}) {
  const { span, depth } = node;
  const color = SPAN_TYPE_COLORS[span.type];
  const { offsetPct, widthPct } = timelinePosition(span, bounds);
  const rowTint = index % 2 === 1 ? "bg-white/[0.02]" : "";
  const showDetails = Boolean(span.error) || hasContent(span.input) || hasContent(span.output);

  return (
    <div className="contents">
      <div
        className={`span-row__label ${rowTint}`}
        style={{
          paddingLeft: `${Math.min(depth, MAX_INDENT_DEPTH) * INDENT_PX + 12}px`,
          borderLeftColor: color,
        }}
      >
        <SpanTypeBadge type={span.type} />
        <span className="span-row__name">{span.name}</span>
        <span className="span-row__meta">{formatDuration(span.duration_ms)}</span>
      </div>

      <div className={`span-row__track ${rowTint}`}>
        <div
          className="waterfall-bar"
          style={{ left: `${offsetPct}%`, width: `${widthPct}%`, backgroundColor: color }}
          title={`${span.name} — ${formatTimestamp(span.started_at)} · ${formatDuration(span.duration_ms)}`}
        />
      </div>

      {showDetails && (
        <div className="span-row__details">
          {span.error && <ErrorBanner error={span.error} />}
          <div className="span-row__payloads">
            <JsonViewer data={span.input} label="input" />
            <JsonViewer data={span.output} label="output" />
          </div>
        </div>
      )}
    </div>
  );
}
