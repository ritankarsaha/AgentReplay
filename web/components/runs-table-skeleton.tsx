import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

export function RunsTableSkeleton() {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {["Status", "Run", "Agent version", "Framework", "Started", "Failure class"].map(
            (label) => (
              <TableCell key={label} className="text-xs font-medium text-muted-foreground">
                {label}
              </TableCell>
            )
          )}
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: 6 }).map((_, i) => (
          <TableRow key={i}>
            {Array.from({ length: 6 }).map((_, j) => (
              <TableCell key={j}>
                <Skeleton className="h-4 w-full max-w-24" />
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
