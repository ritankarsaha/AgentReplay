import { BellRing } from "lucide-react";
import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { getIncidents } from "@/lib/control-plane";
import { getOptionalScope } from "@/lib/viewer";

const POLL_MS = 8000;

export async function OpenIncidentsBanner() {
  const scope = await getOptionalScope();
  if (!scope) return null;

  let open: Awaited<ReturnType<typeof getIncidents>> = [];
  try {
    open = await getIncidents(scope, { status: "open", limit: 5 });
  } catch (err) {
    console.error("[banner] failed to load incidents:", err);
  }

  return (
    <>
      <AutoRefresh intervalMs={POLL_MS} />
      {open.length > 0 && (
        <div role="alert" className="border-b border-status-failure/40 bg-status-failure/10">
          <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-6 py-2 text-sm text-status-failure">
            <BellRing className="size-4 shrink-0 animate-pulse" />
            <span className="font-medium">
              {open.length === 1 ? "1 open incident" : `${open.length} open incidents`}: an agent was halted.
            </span>
            <Link href={`/incidents/${open[0].id}`} className="ml-auto font-medium underline-offset-4 hover:underline">
              Review
            </Link>
          </div>
        </div>
      )}
    </>
  );
}
