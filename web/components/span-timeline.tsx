import { EmptyState } from "@/components/empty-state";
import { SpanRow } from "@/components/span-row";
import { TimelineRuler } from "@/components/timeline-ruler";
import type { SpanOut } from "@/lib/api";
import { computeTimeBounds } from "@/lib/span-timing";
import { flattenSpanTree, type SpanNode } from "@/lib/span-tree";

export function SpanTimeline({ nodes, spans }: { nodes: SpanNode[]; spans: SpanOut[] }) {
  if (nodes.length === 0) {
    return (
      <EmptyState
        title="No spans recorded"
        description="This run has no spans yet — the SDK may still be batching, or the run hasn't made any instrumented calls."
      />
    );
  }

  const flat = flattenSpanTree(nodes);
  const bounds = computeTimeBounds(spans);

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="span-timeline-grid">
        <TimelineRuler bounds={bounds} />
        {flat.map((node, index) => (
          <SpanRow key={node.span.id} node={node} bounds={bounds} index={index} />
        ))}
      </div>
    </div>
  );
}
