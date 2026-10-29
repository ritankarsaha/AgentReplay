import { NextResponse } from "next/server";

import { getPublicBlob } from "@/lib/control-plane";

const SHA256 = /^[0-9a-f]{64}$/;

export async function GET(_request: Request, ctx: RouteContext<"/api/share/[token]/blobs/[sha]">) {
  const { token, sha } = await ctx.params;
  if (!SHA256.test(sha)) return NextResponse.json({ detail: "invalid blob id" }, { status: 400 });

  const blob = await getPublicBlob(token, sha);
  if (!blob) return NextResponse.json({ detail: "not found" }, { status: 404 });
  return new NextResponse(blob.body, {
    headers: {
      "Content-Type": blob.contentType,
      "Cache-Control": "public, max-age=3600",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
    },
  });
}
