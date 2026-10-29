/**
 * Typed server-side client for the AgentReplay ingest API
 * (mirrors `ingest/app/schemas.py`). Reads server-only env vars — never
 * import this from a `"use client"` component.
 */

export type RunStatus = "ok" | "failure" | "divergence" | "halted";
export type SpanType =
  | "llm"
  | "tool"
  | "node"
  | "checkpoint"
  | "policy"
  | "scope_violation"
  | "alert"
  | "message"
  | "data_read"
  | "decision"
  | "negotiation"
  | "screenshot";

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

function getConfig(): { baseUrl: string; serviceToken: string } {
  const baseUrl = process.env.INGEST_API_URL;
  const serviceToken = process.env.INGEST_SERVICE_TOKEN;

  if (!baseUrl || !serviceToken) {
    throw new IngestConfigError(
      "Missing INGEST_API_URL or INGEST_SERVICE_TOKEN. Copy web/.env.example to " +
        "web/.env.local and fill them in (the token must equal the ingest " +
        "service's AGENTREPLAY_INGEST_VIEWER_SERVICE_TOKEN)."
    );
  }

  return { baseUrl, serviceToken };
}

/**
 * Who the viewer is acting for. The ingest API trusts these headers only
 * because they arrive with the server-side service token; `email` always
 * comes from the verified Auth.js session, never from the browser.
 */
export interface ViewerScope {
  email: string;
  projectId?: string;
}

function scopeHeaders(scope: ViewerScope): Record<string, string> {
  const { serviceToken } = getConfig();
  const headers: Record<string, string> = {
    Authorization: `Bearer ${serviceToken}`,
    Accept: "application/json",
    "X-Viewer-Email": scope.email,
  };
  if (scope.projectId) headers["X-Project-Id"] = scope.projectId;
  return headers;
}

export async function ingestFetch<T>(path: string, scope: ViewerScope): Promise<T> {
  const { baseUrl } = getConfig();

  const res = await fetch(`${baseUrl}${path}`, {
    headers: scopeHeaders(scope),
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

export async function ingestFetchBinary(
  path: string,
  scope: ViewerScope | null
): Promise<{ body: ArrayBuffer; contentType: string } | null> {
  const { baseUrl, serviceToken } = getConfig();
  const headers = scope ? scopeHeaders(scope) : { Authorization: `Bearer ${serviceToken}` };
  const res = await fetch(`${baseUrl}${path}`, { headers, cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`ingest ${path} -> ${res.status}`);
  return { body: await res.arrayBuffer(), contentType: res.headers.get("content-type") ?? "application/octet-stream" };
}

export async function ingestFetchPublic<T>(path: string): Promise<T> {
  const { baseUrl, serviceToken } = getConfig();
  const res = await fetch(`${baseUrl}${path}`, {
    headers: { Authorization: `Bearer ${serviceToken}`, Accept: "application/json" },
    cache: "no-store",
  });
  if (res.status === 404) throw new NotFoundError(path);
  if (!res.ok) throw new Error(`ingest ${path} -> ${res.status}`);
  return (await res.json()) as T;
}

export class IngestApiError extends Error {
  constructor(
    public readonly status: number,
    detail: string
  ) {
    super(detail);
  }
}

export async function ingestWrite<T>(
  path: string,
  scope: ViewerScope | null,
  body?: unknown,
  method: "POST" | "DELETE" = "POST"
): Promise<T> {
  const { baseUrl, serviceToken } = getConfig();
  const headers = scope
    ? scopeHeaders(scope)
    : { Authorization: `Bearer ${serviceToken}`, Accept: "application/json" };

  const res = await fetch(`${baseUrl}${path}`, {
    method,
    headers: { ...headers, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });

  if (!res.ok) {
    const parsed = await res.json().catch(() => null);
    const detail =
      (parsed && typeof parsed === "object" && "detail" in parsed && String(parsed.detail)) ||
      `ingest ${path} -> ${res.status}`;
    throw new IngestApiError(res.status, detail);
  }

  return (await res.json()) as T;
}

export interface ProjectOut {
  id: string;
  name: string;
  api_key_prefix: string | null;
  created_at: string;
}

/** Returned once, at creation/rotation -- the plaintext key is never retrievable again. */
export interface ProjectWithKey extends ProjectOut {
  api_key: string;
}

export async function listProjects(email: string): Promise<ProjectOut[]> {
  const data = await ingestFetch<{ projects: ProjectOut[] }>("/v1/account/projects", { email });
  return data.projects;
}

export function createProject(email: string, name: string): Promise<ProjectWithKey> {
  return ingestWrite<ProjectWithKey>("/v1/account/projects", { email }, { name });
}

export function rotateProjectKey(email: string, projectId: string): Promise<ProjectWithKey> {
  return ingestWrite<ProjectWithKey>(
    `/v1/account/projects/${encodeURIComponent(projectId)}/rotate-key`,
    { email }
  );
}

export async function getRuns(scope: ViewerScope, limit = 50): Promise<RunOut[]> {
  const data = await ingestFetch<RunListOut>(`/v1/runs?limit=${limit}`, scope);
  return data.runs;
}

export async function getRun(scope: ViewerScope, runId: string): Promise<RunDetailOut | null> {
  try {
    return await ingestFetch<RunDetailOut>(`/v1/runs/${encodeURIComponent(runId)}`, scope);
  } catch (err) {
    if (err instanceof NotFoundError) return null;
    throw err;
  }
}

export function postGenerateTest(
  scope: ViewerScope,
  runId: string,
  entrypoint: string
): Promise<GenerateTestResult> {
  return ingestWrite<GenerateTestResult>(
    `/v1/runs/${encodeURIComponent(runId)}/generate-test`,
    scope,
    { entrypoint }
  );
}

export async function getLoginEvents(limit = 50): Promise<LoginEventOut[]> {
  const { baseUrl, serviceToken } = getConfig();
  const res = await fetch(`${baseUrl}/v1/auth-events?limit=${limit}`, {
    headers: { Authorization: `Bearer ${serviceToken}`, Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`ingest /v1/auth-events -> ${res.status}: ${await res.text()}`);
  }
  return ((await res.json()) as LoginEventListOut).events;
}

/**
 * Called from `auth.ts`'s `events.signIn` -- best-effort by design (a
 * logging failure must never block a real sign-in), so this throws on
 * failure like every other write here and the caller is responsible for
 * catching it.
 */
export function postLoginEvent(event: {
  email: string;
  name?: string | null;
  image?: string | null;
  provider: string;
}): Promise<LoginEventOut> {
  return ingestWrite<LoginEventOut>("/v1/auth-events", null, event);
}
