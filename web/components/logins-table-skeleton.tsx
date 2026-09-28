import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHeader, TableRow } from "@/components/ui/table";

export function LoginsTableSkeleton() {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {["User", "Provider", "Signed in"].map((label) => (
            <TableCell key={label} className="text-xs font-medium text-muted-foreground">
              {label}
            </TableCell>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: 6 }).map((_, i) => (
          <TableRow key={i}>
            {Array.from({ length: 3 }).map((_, j) => (
              <TableCell key={j}>
                <Skeleton className="h-4 w-full max-w-32" />
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
