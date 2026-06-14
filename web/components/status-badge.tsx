import { CheckCircle2, GitCompare, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { RunStatus } from "@/lib/api";

const STATUS_CLASSES: Record<RunStatus, string> = {
  ok: "border-status-ok/40 text-status-ok bg-status-ok/10",
  failure: "border-status-failure/40 text-status-failure bg-status-failure/10",
  divergence: "border-status-divergence/40 text-status-divergence bg-status-divergence/10",
};

const STATUS_ICONS: Record<RunStatus, typeof CheckCircle2> = {
  ok: CheckCircle2,
  failure: XCircle,
  divergence: GitCompare,
};

export function StatusBadge({ status }: { status: RunStatus }) {
  const Icon = STATUS_ICONS[status];
  return (
    <Badge variant="outline" className={STATUS_CLASSES[status]}>
      <Icon data-icon="inline-start" />
      {status}
    </Badge>
  );
}
