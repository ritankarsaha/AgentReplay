export { auth as proxy } from "@/auth";

/**
 * Gates the whole viewer behind Google sign-in (auth.ts) via the
 * `authorized` callback. Public static assets (icons/manifest referenced
 * by <link> tags in layout.tsx metadata, fetched un-authenticated by
 * browsers/OS before any session exists) must stay excluded alongside
 * `/signin`, NextAuth's own API routes and the read-only `/share/<token>` pages, or they 307 to /signin instead
 * of loading -- found live: favicon.ico was excluded but
 * site.webmanifest/android-chrome-*.png/apple-touch-icon.png weren't.
 */
export const config = {
  matcher: [
    "/((?!api/auth|api/share|share|signin|_next/static|_next/image|favicon\\.ico|favicon-16x16\\.png|favicon-32x32\\.png|android-chrome-192x192\\.png|android-chrome-512x512\\.png|apple-touch-icon\\.png|site\\.webmanifest).*)",
  ],
};
