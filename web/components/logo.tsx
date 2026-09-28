import Image from "next/image";

import { cn } from "@/lib/utils";

/** The AgentReplay app icon (public/android-chrome-192x192.png). */
export function Logo({ className }: { className?: string }) {
  return (
    <Image
      src="/android-chrome-192x192.png"
      alt="AgentReplay"
      width={192}
      height={192}
      priority
      className={cn("size-6 shrink-0 rounded-md", className)}
    />
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-mono text-sm font-semibold tracking-tight", className)}>
      <span className="text-foreground">Agent</span>
      <span className="text-muted-foreground">Replay</span>
    </span>
  );
}
