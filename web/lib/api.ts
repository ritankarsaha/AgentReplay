/**
 * Typed server-side client for the AgentReplay ingest API
 * (mirrors `ingest/app/schemas.py`). Reads server-only env vars — never
 * import this from a `"use client"` component.
 */

export type RunStatus = "ok" | "failure" | "divergence";
export type SpanType = "llm" | "tool" | "node" | "checkpoint";

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
}

export interface SpanOut {
  id: string;
  run_id: string;
  parent_id: string | null;
  type: SpanType;
  name: string;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
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
