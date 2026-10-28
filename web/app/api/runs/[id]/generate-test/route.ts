import { NextResponse } from "next/server";

import { IngestApiError, postGenerateTest } from "@/lib/api";
import { projectScopeOrNull } from "@/lib/viewer";

export async function POST(
  request: Request,
  ctx: RouteContext<"/api/runs/[id]/generate-test">
) {
  const { id } = await ctx.params;

  // Never trust a project id from the browser: scope comes from the verified
  // session + selected-project cookie, and ingest re-checks ownership.
  const scope = await projectScopeOrNull();
  if (!scope) {
    return NextResponse.json({ detail: "not signed in or no project selected" }, { status: 401 });
  }

  let entrypoint: unknown;
  try {
    const body = await request.json();
    entrypoint = body?.entrypoint;
  } catch {
    return NextResponse.json({ detail: "invalid JSON body" }, { status: 400 });
  }

  if (typeof entrypoint !== "string" || entrypoint.trim() === "") {
    return NextResponse.json({ detail: "entrypoint is required" }, { status: 400 });
  }

  try {
    const result = await postGenerateTest(scope, id, entrypoint.trim());
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof IngestApiError) {
      return NextResponse.json({ detail: err.message }, { status: err.status });
    }
    const message = err instanceof Error ? err.message : "unknown error";
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}
