import Link from "next/link";

import { Logo, Wordmark } from "@/components/logo";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-10 border-b border-border bg-background/75 backdrop-blur-md">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-3">
        <Link href="/" className="flex items-center gap-2.5">
          <Logo />
          <Wordmark />
        </Link>
        <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full rounded-full bg-status-ok animate-[pulse-rec_2s_ease-in-out_infinite]" />
            <span className="relative inline-flex size-2 rounded-full bg-status-ok" />
          </span>
          recording
        </div>
      </div>
    </header>
  );
}
