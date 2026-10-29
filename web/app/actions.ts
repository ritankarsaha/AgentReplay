"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";

import { auth } from "@/auth";
import {
  IngestApiError,
  createProject,
  listProjects,
  rotateProjectKey,
  type ProjectWithKey,
} from "@/lib/api";
import { disableShare, enableShare, resolveIncident } from "@/lib/control-plane";
import { PROJECT_COOKIE, projectScopeOrNull } from "@/lib/viewer";

export type KeyActionState =
  | { status: "idle" }
  | { status: "error"; message: string }
  | { status: "created"; project: ProjectWithKey; rotated: boolean };

async function requireEmail(): Promise<string> {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) throw new Error("not signed in");
  return email;
}

async function rememberProject(projectId: string) {
  (await cookies()).set(PROJECT_COOKIE, projectId, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
  });
}

function errorState(err: unknown): KeyActionState {
  if (err instanceof IngestApiError) return { status: "error", message: err.message };
  return { status: "error", message: "Something went wrong. Please try again." };
}

export async function createProjectAction(
  _prev: KeyActionState,
  formData: FormData
): Promise<KeyActionState> {
  const name = String(formData.get("name") ?? "").trim();
  if (!name) return { status: "error", message: "Give your project a name." };
  if (name.length > 80) return { status: "error", message: "Name is too long (max 80)." };

  try {
    const email = await requireEmail();
    const project = await createProject(email, name);
    await rememberProject(project.id);
    revalidatePath("/", "layout");
    return { status: "created", project, rotated: false };
  } catch (err) {
    return errorState(err);
  }
}

export async function rotateKeyAction(
  _prev: KeyActionState,
  formData: FormData
): Promise<KeyActionState> {
  const projectId = String(formData.get("projectId") ?? "");
  try {
    const email = await requireEmail();
    const project = await rotateProjectKey(email, projectId);
    revalidatePath("/projects");
    return { status: "created", project, rotated: true };
  } catch (err) {
    return errorState(err);
  }
}

export async function selectProjectAction(projectId: string): Promise<void> {
  const email = await requireEmail();
  // Only remember projects this user actually owns.
  const owned = (await listProjects(email)).some((p) => p.id === projectId);
  if (!owned) return;
  await rememberProject(projectId);
  revalidatePath("/", "layout");
}

export type IncidentActionResult = { ok: true; shareToken: string | null } | { ok: false; message: string };

async function incidentScope() {
  const scope = await projectScopeOrNull();
  if (!scope) throw new Error("not signed in or no project selected");
  return scope;
}

export async function setIncidentShareAction(incidentId: string, enabled: boolean): Promise<IncidentActionResult> {
  try {
    const scope = await incidentScope();
    const { share_token } = enabled ? await enableShare(scope, incidentId) : await disableShare(scope, incidentId);
    revalidatePath(`/incidents/${incidentId}`);
    return { ok: true, shareToken: share_token };
  } catch (err) {
    return { ok: false, message: err instanceof IngestApiError ? err.message : "Could not update sharing." };
  }
}

export async function resolveIncidentAction(incidentId: string): Promise<IncidentActionResult> {
  try {
    const scope = await incidentScope();
    await resolveIncident(scope, incidentId);
    revalidatePath("/", "layout");
    return { ok: true, shareToken: null };
  } catch (err) {
    return { ok: false, message: err instanceof IngestApiError ? err.message : "Could not resolve the incident." };
  }
}
