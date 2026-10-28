import { cache } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { listProjects, type ProjectOut, type ViewerScope } from "@/lib/api";

export const PROJECT_COOKIE = "ar_project";

const ADMIN_EMAILS = (process.env.AUTH_ADMIN_EMAILS ?? "")
  .split(",")
  .map((email) => email.trim().toLowerCase())
  .filter(Boolean);

export function isAdminEmail(email: string | null | undefined): boolean {
  return !!email && ADMIN_EMAILS.includes(email.toLowerCase());
}

export interface ViewerContext {
  email: string;
  projects: ProjectOut[];
  /** The project the UI is currently scoped to, or null if the user has none yet. */
  active: ProjectOut | null;
}

/**
 * The signed-in user's projects and which one is selected (the `ar_project`
 * cookie, falling back to their first). Memoized per request. The cookie is
 * only a preference: every ingest call re-checks ownership server-side, so
 * a forged cookie can at worst select nothing.
 */
export const getViewerContext = cache(async (): Promise<ViewerContext> => {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect("/signin");

  const projects = await listProjects(email);
  const selected = (await cookies()).get(PROJECT_COOKIE)?.value;
  const active = projects.find((p) => p.id === selected) ?? projects[0] ?? null;
  return { email, projects, active };
});

/** Scope for project-bound data; sends users with no project to create one. */
export async function requireProjectScope(): Promise<ViewerScope> {
  const { email, active } = await getViewerContext();
  if (!active) redirect("/projects");
  return { email, projectId: active.id };
}

/** Same, for route handlers, where a redirect is the wrong response. */
export async function projectScopeOrNull(): Promise<ViewerScope | null> {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) return null;
  const { active } = await getViewerContext();
  return active ? { email, projectId: active.id } : null;
}
