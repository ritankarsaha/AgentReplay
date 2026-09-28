import Link from "next/link";
import Image from "next/image";
import { LogOut, Users } from "lucide-react";

import { auth, signOut } from "@/auth";
import { Logo, Wordmark } from "@/components/logo";
import { Button } from "@/components/ui/button";

export async function SiteHeader() {
  const session = await auth();

  return (
    <header className="sticky top-0 z-10 border-b border-border bg-background/75 backdrop-blur-md">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-6">
          <Link href="/" className="flex items-center gap-2.5">
            <Logo />
            <Wordmark />
          </Link>
          <Link
            href="/logins"
            className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <Users className="size-3.5" />
            Logins
          </Link>
        </div>
        <div className="flex items-center gap-4">
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
