import { formatAbsolute, formatRelativeTime } from "@/lib/format";

export function RelativeTime({ iso }: { iso: string }) {
  return (
    <time dateTime={iso} title={formatAbsolute(iso)} className="text-muted-foreground">
      {formatRelativeTime(iso)}
    </time>
  );
}
