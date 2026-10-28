"use client";

import { useActionState } from "react";
import { Loader2, Plus, RefreshCw } from "lucide-react";

import {
  createProjectAction,
  rotateKeyAction,
  type KeyActionState,
} from "@/app/actions";
import { KeyReveal } from "@/components/key-reveal";
import { Button } from "@/components/ui/button";

const IDLE: KeyActionState = { status: "idle" };

export function CreateProjectForm({ firstProject }: { firstProject: boolean }) {
  const [state, action, pending] = useActionState(createProjectAction, IDLE);

  return (
    <div className="flex flex-col gap-4">
      <form action={action} className="flex flex-wrap items-center gap-2">
        <input
          name="name"
          required
          maxLength={80}
          placeholder={firstProject ? "e.g. Support agent" : "New project name"}
          aria-label="Project name"
          className="h-8 min-w-56 flex-1 rounded-md border border-border bg-background px-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        />
        <Button type="submit" disabled={pending}>
          {pending ? <Loader2 className="animate-spin" /> : <Plus />}
          Create project
        </Button>
      </form>
      {state.status === "error" && (
        <p className="text-xs text-status-failure">{state.message}</p>
      )}
      {state.status === "created" && <KeyReveal project={state.project} rotated={false} />}
    </div>
  );
}

export function RotateKeyForm({ projectId }: { projectId: string }) {
  const [state, action, pending] = useActionState(rotateKeyAction, IDLE);

  return (
    <div className="flex flex-col gap-3">
      <form
        action={action}
        onSubmit={(event) => {
          if (!window.confirm("Rotate this key? The current key stops working immediately.")) {
            event.preventDefault();
          }
        }}
      >
        <input type="hidden" name="projectId" value={projectId} />
        <Button type="submit" variant="outline" size="sm" disabled={pending}>
          {pending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
          Rotate key
        </Button>
      </form>
      {state.status === "error" && (
        <p className="text-xs text-status-failure">{state.message}</p>
      )}
      {state.status === "created" && <KeyReveal project={state.project} rotated />}
    </div>
  );
}
