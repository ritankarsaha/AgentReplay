import { NextResponse } from "next/server";

import { getBlob } from "@/lib/control-plane";
import { projectScopeOrNull } from "@/lib/viewer";

const SHA256 = /^[0-9a-f]{64}$/;

export async function GET(_request: Request, ctx: RouteContext<"/api/blobs/[sha]">) {
  const { sha } = await ctx.params;
  if (!SHA256.test(sha)) return NextResponse.json({ detail: "invalid blob id" }, { status: 400 });

  const scope = await projectScopeOrNull();
  if (!scope) return NextResponse.json({ detail: "not signed in or no project selected" }, { status: 401 });

  const blob = await getBlob(scope, sha);
  if (!blob) return NextResponse.json({ detail: "not found" }, { status: 404 });
  return new NextResponse(blob.body, {
    headers: {
      "Content-Type": blob.contentType,
      "Cache-Control": "private, max-age=31536000, immutable",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
    },
  });
}
