import { IncidentList } from "@/components/incident-list";
import { getIncidents } from "@/lib/control-plane";
import { requireProjectScope } from "@/lib/viewer";

export default async function IncidentsPage() {
  const scope = await requireProjectScope();
  const incidents = await getIncidents(scope, { limit: 100 });
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-10">
      <div>
        <h1 className="text-lg font-semibold">Incidents</h1>
        <p className="text-sm text-muted-foreground">Runs the scope guard or spend gate halted.</p>
      </div>
      <IncidentList incidents={incidents} />
    </main>
  );
}
