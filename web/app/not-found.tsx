import Link from "next/link";

import { EmptyState } from "@/components/empty-state";

export default function NotFound() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <EmptyState title="Page not found" description="The page you're looking for doesn't exist." />
      <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
        ← Runs
      </Link>
    </main>
  );
}
