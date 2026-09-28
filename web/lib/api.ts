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

export interface AssertionSpec {
  must_call_tools: string[];
  must_not_call_tools: string[];
  max_steps: number | null;
  no_exception: boolean;
  rationale: string;
  model: string;

  semantic_rubric: string | null;
}

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
  assertion_spec?: AssertionSpec;
}


export interface GenerateTestResult {
  run_id: string;
  fixture_filename: string;
  fixture_source: string;
  test_filename: string;
  test_source: string;
  assertion_spec: AssertionSpec | null;
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

export interface LoginEventOut {
  id: string;
  project_id: string;
  email: string;
  name: string | null;
  image: string | null;
  provider: string;
  created_at: string;
}

interface LoginEventListOut {
  events: LoginEventOut[];
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

export class IngestApiError extends Error {
  constructor(
    public readonly status: number,
    detail: string
  ) {
    super(detail);
  }
}

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

export async function postGenerateTest(
  runId: string,
  entrypoint: string
): Promise<GenerateTestResult> {
  const { baseUrl, apiKey } = getConfig();

  const res = await fetch(`${baseUrl}/v1/runs/${encodeURIComponent(runId)}/generate-test`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ entrypoint }),
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail =
      (body && typeof body === "object" && "detail" in body && String(body.detail)) ||
      `ingest generate-test -> ${res.status}`;
    throw new IngestApiError(res.status, detail);
  }

  return (await res.json()) as GenerateTestResult;
}

export async function getLoginEvents(limit = 50): Promise<LoginEventOut[]> {
  const data = await ingestFetch<LoginEventListOut>(`/v1/auth-events?limit=${limit}`);
  return data.events;
}

/**
 * Called from `auth.ts`'s `events.signIn` -- best-effort by design (a
 * logging failure must never block a real sign-in), so this throws on
 * failure like every other write here and the caller is responsible for
 * catching it.
 */
export async function postLoginEvent(event: {
  email: string;
  name?: string | null;
  image?: string | null;
  provider: string;
}): Promise<LoginEventOut> {
  const { baseUrl, apiKey } = getConfig();

  const res = await fetch(`${baseUrl}/v1/auth-events`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(event),
    cache: "no-store",
  });

  if (!res.ok) {
    const body = await res.text();
    throw new IngestApiError(res.status, `ingest auth-events -> ${res.status}: ${body}`);
  }

  return (await res.json()) as LoginEventOut;
}
