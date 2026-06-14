import { Skeleton } from "@/components/ui/skeleton";

export default function RunDetailLoading() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <Skeleton className="h-4 w-16" />
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-16 w-full" />
      <div className="overflow-hidden rounded-lg border border-border">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="grid grid-cols-[minmax(220px,32%)_1fr] gap-3 border-b border-border p-3 last:border-b-0">
            <Skeleton className="h-6" style={{ marginLeft: `${(i % 3) * 1.25}rem` }} />
            <Skeleton className="h-6" />
          </div>
        ))}
      </div>
    </main>
  );
}
