/**
 * Typed server-side client for the AgentReplay ingest API
 * (mirrors `ingest/app/schemas.py`). Reads server-only env vars — never
 * import this from a `"use client"` component.
 */

export type RunStatus = "ok" | "failure" | "divergence";
export type SpanType = "llm" | "tool" | "node" | "checkpoint";

// Chunk 3.6 (Sonnet/MAST classifier). "none" = not classified yet (either
// not a failure, or a failure not yet picked up by a Celery worker) —
// distinct from "done"/"error" so the UI can show a "classifying…" state.
export type ClassificationStatus = "none" | "done" | "error";

export interface SuggestedAssertion {
  type: "exact" | "structural" | "semantic";
  description: string;
}

// The full `runs.diagnosis` JSONB blob (`ingest/app/classifier.py`). On a
// successful classification every field through `classified_at` is
// present; on a classifier error only `error`/`backend`/`attempted_at` are.
export interface Diagnosis {
  failure_class?: string;
  culprit_span_id?: string | null;
  text?: string;
  suggested_assertion?: SuggestedAssertion;
  model?: string;
  backend?: string;
  classified_at?: string;
  error?: string;
  attempted_at?: string;
}

export interface RunOut {
  id: string;
  project_id: string;
  agent_version: string | null;
  framework: string | null;
  started_at: string;
  last_seen_at: string;
  status: RunStatus;
  failure_class: string | null;
  root_span_id: string | null;
  metadata: Record<string, unknown>;
  classification_status: ClassificationStatus;
  diagnosis: Diagnosis | null;
}

export interface SpanOut {
  id: string;
  run_id: string;
  parent_id: string | null;
  type: SpanType;
  name: string;
  input: Record<string, unknown>;
  // Any JSON value: a `@agentreplay.tool`-decorated function can return a
  // list/string/number/etc., not just an object (mirrors SpanOut.output in
  // ingest/app/schemas.py).
  output: unknown;
  error: { type: string; message: string } | null;
  started_at: string;
  duration_ms: number;
  fingerprint: string | null;
}

export interface RunDetailOut extends RunOut {
  spans: SpanOut[];
}

interface RunListOut {
  runs: RunOut[];
}

class IngestConfigError extends Error {}

function getConfig(): { baseUrl: string; apiKey: string } {
  const baseUrl = process.env.INGEST_API_URL;
  const apiKey = process.env.INGEST_API_KEY;

  if (!baseUrl || !apiKey) {
    throw new IngestConfigError(
      "Missing INGEST_API_URL or INGEST_API_KEY. Copy web/.env.example to " +
        "web/.env.local and fill in the values from " +
        "ingest/scripts/create_project.py."
    );
  }

  return { baseUrl, apiKey };
}

async function ingestFetch<T>(path: string): Promise<T> {
  const { baseUrl, apiKey } = getConfig();

  const res = await fetch(`${baseUrl}${path}`, {
    headers: {
      Authorization: `Bearer ${apiKey}`,
      Accept: "application/json",
    },
    cache: "no-store",
  });

  if (res.status === 404) {
    throw new NotFoundError(path);
  }

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`ingest ${path} -> ${res.status}: ${body}`);
  }

  return (await res.json()) as T;
}

export class NotFoundError extends Error {}

export async function getRuns(limit = 50): Promise<RunOut[]> {
  const data = await ingestFetch<RunListOut>(`/v1/runs?limit=${limit}`);
  return data.runs;
}

export async function getRun(runId: string): Promise<RunDetailOut | null> {
  try {
    return await ingestFetch<RunDetailOut>(`/v1/runs/${encodeURIComponent(runId)}`);
  } catch (err) {
    if (err instanceof NotFoundError) return null;
    throw err;
  }
}
