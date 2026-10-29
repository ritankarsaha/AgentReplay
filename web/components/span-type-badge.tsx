import {
  BellRing,
  Bookmark,
  Camera,
  FileText,
  GitBranch,
  Handshake,
  MessageSquare,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { SpanType } from "@/lib/api";

const SPAN_TYPE_CLASSES: Record<SpanType, string> = {
  node: "border-span-node/40 text-span-node bg-span-node/10",
  llm: "border-span-llm/40 text-span-llm bg-span-llm/10",
  tool: "border-span-tool/40 text-span-tool bg-span-tool/10",
  checkpoint: "border-span-checkpoint/40 text-span-checkpoint bg-span-checkpoint/10",
  policy: "border-span-policy/40 text-span-policy bg-span-policy/10",
  scope_violation: "border-status-failure/40 text-status-failure bg-status-failure/10",
  alert: "border-status-failure/40 text-status-failure bg-status-failure/10",
  message: "border-span-message/40 text-span-message bg-span-message/10",
  data_read: "border-span-data/40 text-span-data bg-span-data/10",
  decision: "border-span-llm/40 text-span-llm bg-span-llm/10",
  negotiation: "border-span-negotiation/40 text-span-negotiation bg-span-negotiation/10",
  screenshot: "border-span-node/40 text-span-node bg-span-node/10",
};

const SPAN_TYPE_ICONS: Record<SpanType, typeof GitBranch> = {
  node: GitBranch,
  llm: Sparkles,
  tool: Wrench,
  checkpoint: Bookmark,
  policy: ShieldCheck,
  scope_violation: ShieldAlert,
  alert: BellRing,
  message: MessageSquare,
  data_read: FileText,
  decision: Scale,
  negotiation: Handshake,
  screenshot: Camera,
};

export function SpanTypeBadge({ type }: { type: SpanType }) {
  const Icon = SPAN_TYPE_ICONS[type] ?? Bookmark;
  return (
    <Badge variant="outline" className={`font-mono ${SPAN_TYPE_CLASSES[type] ?? ""}`}>
      <Icon data-icon="inline-start" />
      {type}
    </Badge>
  );
}
