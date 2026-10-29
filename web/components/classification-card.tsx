import { Stethoscope } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Classification } from "@/lib/control-plane";

export function ClassificationCard({ classification, notes }: { classification: Classification | null | undefined; notes?: string[] }) {
  const unavailable = notes?.find((n) => n.startsWith("classification unavailable"));
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Stethoscope className="size-4 text-muted-foreground" />
          Classification
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {classification ? (
          <>
            <span className="font-mono text-sm font-medium text-status-failure">{classification.failure_class}</span>
            {classification.diagnosis && <p className="text-sm text-foreground">{classification.diagnosis}</p>}
            <span className="font-mono text-xs text-muted-foreground">
              {classification.model} ({classification.backend}) · MAST taxonomy
            </span>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{unavailable ?? "Not classified."}</p>
        )}
      </CardContent>
    </Card>
  );
}
