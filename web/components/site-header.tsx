import { cookies } from "next/headers";
import Link from "next/link";
import Image from "next/image";
import { FolderKanban, LogOut, Users } from "lucide-react";

import { auth, signOut } from "@/auth";
import { Logo, Wordmark } from "@/components/logo";
import { ProjectSwitcher } from "@/components/project-switcher";
import { Button } from "@/components/ui/button";
import { listProjects, type ProjectOut } from "@/lib/api";
import { PROJECT_COOKIE, isAdminEmail } from "@/lib/viewer";

export async function SiteHeader() {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();

  // The header also renders on /signin, so this must never redirect, and a
  // backend hiccup must not take the whole page down with it.
  let projects: ProjectOut[] = [];
  if (email) {
    try {
      projects = await listProjects(email);
    } catch (err) {
      console.error("[header] failed to load projects:", err);
    }
  }
  const selected = email ? (await cookies()).get(PROJECT_COOKIE)?.value : undefined;
  const activeId = (projects.find((p) => p.id === selected) ?? projects[0])?.id;

  return (
    <header className="sticky top-0 z-10 border-b border-border bg-background/75 backdrop-blur-md">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-6">
          <Link href="/" className="flex items-center gap-2.5">
            <Logo />
            <Wordmark />
          </Link>
          {email && (
            <Link
              href="/projects"
              className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              <FolderKanban className="size-3.5" />
              Projects
            </Link>
          )}
          {isAdminEmail(email) && (
            <Link
              href="/logins"
              className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              <Users className="size-3.5" />
              Logins
            </Link>
          )}
        </div>
        <div className="flex items-center gap-4">
          {activeId && <ProjectSwitcher projects={projects} activeId={activeId} />}
          <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
            <span className="relative flex size-2">
              <span className="absolute inline-flex size-full rounded-full bg-status-ok animate-[pulse-rec_2s_ease-in-out_infinite]" />
              <span className="relative inline-flex size-2 rounded-full bg-status-ok" />
            </span>
            recording
          </div>
          {session?.user && (
            <div className="flex items-center gap-2.5 border-l border-border pl-4">
              {session.user.image && (
                <Image
                  src={session.user.image}
                  alt={session.user.name ?? "Signed-in user"}
                  width={22}
                  height={22}
                  className="rounded-full"
                  referrerPolicy="no-referrer"
                />
              )}
              <span className="hidden text-xs text-muted-foreground sm:inline">
                {session.user.email}
              </span>
              <form
                action={async () => {
                  "use server";
                  await signOut({ redirectTo: "/signin" });
                }}
              >
                <Button type="submit" variant="ghost" size="icon-sm" aria-label="Sign out">
                  <LogOut />
                </Button>
              </form>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
