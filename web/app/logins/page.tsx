import { Suspense } from "react";

import { EmptyState } from "@/components/empty-state";
import { LoginsTable } from "@/components/logins-table";
import { LoginsTableSkeleton } from "@/components/logins-table-skeleton";
import { notFound } from "next/navigation";

import { getLoginEvents } from "@/lib/api";
import { getViewerContext, isAdminEmail } from "@/lib/viewer";

async function LoginsTableSection() {
  const events = await getLoginEvents();

  if (events.length === 0) {
    return (
      <EmptyState
        title="No sign-ins yet"
        description="Google sign-ins to this viewer will appear here."
      />
    );
  }

  return <LoginsTable events={events} />;
}

export default async function LoginsPage() {
  // Operator-only: this lists every user's email across all tenants.
  const { email } = await getViewerContext();
  if (!isAdminEmail(email)) notFound();

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <div>
        <h1 className="text-lg font-semibold">Logins</h1>
        <p className="text-sm text-muted-foreground">
          Everyone who has signed in to this viewer (operators only).
        </p>
      </div>
      <Suspense fallback={<LoginsTableSkeleton />}>
        <LoginsTableSection />
      </Suspense>
    </main>
  );
}
