"use client";

import { useTransition } from "react";

import { selectProjectAction } from "@/app/actions";

export function ProjectSwitcher({
  projects,
  activeId,
}: {
  projects: { id: string; name: string }[];
  activeId: string;
}) {
  const [pending, startTransition] = useTransition();

  if (projects.length < 2) {
    return (
      <span className="font-mono text-xs text-muted-foreground">{projects[0]?.name}</span>
    );
  }

  return (
    <select
      aria-label="Active project"
      value={activeId}
      disabled={pending}
      onChange={(event) => {
        const id = event.target.value;
        startTransition(async () => {
          await selectProjectAction(id);
        });
      }}
      className="h-7 rounded-md border border-border bg-background px-2 font-mono text-xs text-foreground disabled:opacity-60"
    >
      {projects.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  );
}
