import type { SpanOut } from "./api";

export interface SpanNode {
  span: SpanOut;
  children: SpanNode[];
  depth: number;
}

/**
 * Build the `parent_id` tree out of a flat span list.
 *
 * Spans whose `parent_id` is null, or points at a span not present in
 * `spans` (shouldn't happen given the schema, but the ingest API doesn't
 * guarantee it), are treated as roots. Siblings (and the root list) are
 * sorted by `started_at` ascending so the tree reads in execution order.
 */
export function buildSpanTree(spans: SpanOut[]): SpanNode[] {
  const nodes = new Map<string, SpanNode>();
  for (const span of spans) {
    nodes.set(span.id, { span, children: [], depth: 0 });
  }

  const roots: SpanNode[] = [];

  for (const node of nodes.values()) {
    const parent = node.span.parent_id ? nodes.get(node.span.parent_id) : undefined;
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }

  const sortByStart = (a: SpanNode, b: SpanNode) =>
    a.span.started_at < b.span.started_at ? -1 : a.span.started_at > b.span.started_at ? 1 : 0;

  // Sort siblings into execution order and assign depths in the same pass
  // (depth is only knowable top-down, after parent/child edges are wired).
  const sortAndAssignDepth = (list: SpanNode[], depth: number) => {
    list.sort(sortByStart);
    for (const node of list) {
      node.depth = depth;
      sortAndAssignDepth(node.children, depth + 1);
    }
  };
  sortAndAssignDepth(roots, 0);

  return roots;
}

/** Flatten a span tree into execution order (DFS preorder), `depth` intact. */
export function flattenSpanTree(nodes: SpanNode[]): SpanNode[] {
  const result: SpanNode[] = [];

  const visit = (list: SpanNode[]) => {
    for (const node of list) {
      result.push(node);
      visit(node.children);
    }
  };
  visit(nodes);

  return result;
}
