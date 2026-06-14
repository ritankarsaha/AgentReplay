import Link from "next/link";

import { EmptyState } from "@/components/empty-state";

export default function RunNotFound() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <div>
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
          ← Runs
        </Link>
      </div>
      <EmptyState
        title="Run not found"
        description="Check the run id, or it may belong to a different project's API key."
      />
    </main>
  );
}
