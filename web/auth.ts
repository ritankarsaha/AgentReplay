import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

import { postLoginEvent } from "@/lib/api";

/**
 * Google sign-in for the viewer. Any Google account can sign in (self-serve
 * hosted): tenant isolation is NOT this file's job -- every data request
 * carries the verified email to the ingest API, which only returns projects
 * that email owns. `AUTH_ALLOWED_EMAILS` remains as a private-beta switch
 * (set it to restrict sign-in to a list; leave unset for open signup).
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
