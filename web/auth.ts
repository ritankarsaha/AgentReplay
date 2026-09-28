import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

import { postLoginEvent } from "@/lib/api";

/**
 * Google sign-in for the viewer (replaces the HTTP Basic Auth stopgap in
 * the prior `middleware.ts`). Any Google account can sign in -- this is a
 * deliberate, explicit project-owner choice, not a default: the viewer
 * shows real production LLM traces, so this is a much weaker boundary than
 * an allow-list. `ALLOWED_EMAILS` below is the one-line hook to tighten
 * that later without restructuring anything.
 */
const ALLOWED_EMAILS = process.env.AUTH_ALLOWED_EMAILS?.split(",")
  .map((email) => email.trim().toLowerCase())
  .filter(Boolean);

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  pages: {
    signIn: "/signin",
  },
  callbacks: {
    async signIn({ user }) {
      if (!ALLOWED_EMAILS || ALLOWED_EMAILS.length === 0) return true;
      return !!user.email && ALLOWED_EMAILS.includes(user.email.toLowerCase());
    },
    // Read by the `auth`-as-middleware wrapper (middleware.ts): returning
    // `false` here is what makes NextAuth redirect an unauthenticated
    // request to `pages.signIn` automatically -- without this callback,
    // `auth` as middleware only attaches session data and never enforces
    // anything on its own.
    authorized({ auth }) {
      return !!auth?.user;
    },
  },
  events: {
    // Sessions here are JWT-only (no database adapter), so without this
    // there is no durable record anywhere of who has signed in -- this is
    // the entire source of the `/logins` table. Best-effort: a failure to
    // record a login must never break the login itself.
    async signIn({ user, account }) {
      if (!user.email) return;
      try {
        await postLoginEvent({
          email: user.email,
          name: user.name,
          image: user.image,
          provider: account?.provider ?? "unknown",
        });
      } catch (err) {
        console.error("[auth] failed to record login event:", err);
      }
    },
  },
});
