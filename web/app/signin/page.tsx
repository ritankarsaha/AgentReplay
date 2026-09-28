import { AlertTriangle } from "lucide-react";

import { auth, signIn } from "@/auth";
import { GoogleSignInButton } from "@/components/google-signin-button";
import { Logo, Wordmark } from "@/components/logo";
import { redirect } from "next/navigation";

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; callbackUrl?: string }>;
}) {
  const session = await auth();
  const { error, callbackUrl } = await searchParams;

  if (session) {
    redirect(callbackUrl || "/");
  }

  return (
    <div className="relative flex min-h-[calc(100vh-3.5rem)] items-center justify-center overflow-hidden px-6">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          backgroundImage:
            "radial-gradient(circle at 15% 20%, color-mix(in oklch, var(--span-llm), transparent 88%), transparent 45%)," +
            "radial-gradient(circle at 85% 75%, color-mix(in oklch, var(--span-tool), transparent 88%), transparent 45%)",
        }}
      />

      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex items-center gap-2.5">
            <Logo className="size-9" />
          </div>
          <div>
            <Wordmark className="text-lg" />
            <p className="mt-1.5 font-mono text-xs text-muted-foreground">
              The flight recorder for AI agents.
            </p>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-6 ring-1 ring-foreground/10">
          <h1 className="text-center text-sm font-medium text-card-foreground">
            Sign in to continue
          </h1>
          <p className="mt-1 text-center text-xs text-muted-foreground">
            Access to production run traces requires a Google account.
          </p>

          <form
            className="mt-5"
            action={async () => {
              "use server";
              await signIn("google", { redirectTo: callbackUrl || "/" });
            }}
          >
            <GoogleSignInButton />
          </form>

          {error && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-status-failure/30 bg-status-failure/10 px-3 py-2 text-xs text-status-failure">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              <span>
                {error === "AccessDenied"
                  ? "This Google account isn't authorized to view this project."
                  : "Sign-in failed. Please try again."}
              </span>
            </div>
          )}
        </div>

        <p className="mt-6 text-center font-mono text-[0.7rem] text-muted-foreground">
          recorded traces may contain sensitive production data
        </p>
      </div>
    </div>
  );
}
