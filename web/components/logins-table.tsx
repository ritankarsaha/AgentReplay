import Image from "next/image";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { RelativeTime } from "@/components/relative-time";
import type { LoginEventOut } from "@/lib/api";

export function LoginsTable({ events }: { events: LoginEventOut[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>User</TableHead>
          <TableHead>Provider</TableHead>
          <TableHead>Signed in</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {events.map((event) => (
          <TableRow key={event.id} className="transition-colors hover:bg-muted/40">
            <TableCell>
              <div className="flex items-center gap-2.5">
                {event.image ? (
                  <Image
                    src={event.image}
                    alt={event.name ?? event.email}
                    width={24}
                    height={24}
                    className="rounded-full"
                    referrerPolicy="no-referrer"
                  />
                ) : (
                  <div className="size-6 shrink-0 rounded-full bg-muted" aria-hidden="true" />
                )}
                <div className="flex flex-col">
                  <span className="text-sm text-foreground">{event.name ?? "—"}</span>
                  <span className="font-mono text-xs text-muted-foreground">{event.email}</span>
                </div>
              </div>
            </TableCell>
            <TableCell>
              <Badge variant="outline" className="capitalize">
                {event.provider}
              </Badge>
            </TableCell>
            <TableCell>
              <RelativeTime iso={event.created_at} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
