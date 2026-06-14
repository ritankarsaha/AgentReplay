import { Bookmark, GitBranch, Sparkles, Wrench } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { SpanType } from "@/lib/api";

const SPAN_TYPE_CLASSES: Record<SpanType, string> = {
  node: "border-span-node/40 text-span-node bg-span-node/10",
  llm: "border-span-llm/40 text-span-llm bg-span-llm/10",
  tool: "border-span-tool/40 text-span-tool bg-span-tool/10",
  checkpoint: "border-span-checkpoint/40 text-span-checkpoint bg-span-checkpoint/10",
};

const SPAN_TYPE_ICONS: Record<SpanType, typeof GitBranch> = {
  node: GitBranch,
  llm: Sparkles,
  tool: Wrench,
  checkpoint: Bookmark,
};

export function SpanTypeBadge({ type }: { type: SpanType }) {
  const Icon = SPAN_TYPE_ICONS[type];
  return (
    <Badge variant="outline" className={`font-mono ${SPAN_TYPE_CLASSES[type]}`}>
      <Icon data-icon="inline-start" />
      {type}
    </Badge>
  );
}
