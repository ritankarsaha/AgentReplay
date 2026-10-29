import { cn } from "@/lib/utils";

export type TagTone = "ok" | "bad" | "warn" | "info" | "sim" | "muted";

const TONES: Record<TagTone, string> = {
  ok: "border-status-ok/40 bg-status-ok/10 text-status-ok",
  bad: "border-status-failure/40 bg-status-failure/10 text-status-failure",
  warn: "border-status-divergence/40 bg-status-divergence/10 text-status-divergence",
  info: "border-span-node/40 bg-span-node/10 text-span-node",
  sim: "border-span-data/40 bg-span-data/10 text-span-data",
  muted: "border-border text-muted-foreground",
};

export function Tag({
  tone = "muted",
  className,
  children,
  title,
}: {
  tone?: TagTone;
  className?: string;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-5 w-fit shrink-0 items-center gap-1 whitespace-nowrap rounded-4xl border px-2 text-xs font-medium [&>svg]:size-3",
        TONES[tone],
        className
      )}
    >
      {children}
    </span>
  );
}
