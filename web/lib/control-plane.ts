/**
 * Typed server-side client for the control-plane endpoints of the ingest API
 * (agents, manifests, trust, incidents, filings, scoreboard). Server-only.
 */

import {
  NotFoundError,
  ingestFetch,
  ingestFetchBinary,
  ingestFetchPublic,
  ingestWrite,
  type ViewerScope,
} from "./api";

export interface AgentOut {
  id: string;
  name: string;
  public_key: string;
  status: string;
  owner_id: string | null;
  created_at: string | null;
}

export interface Constraints {
  max_spend_inr?: number;
  max_bookings_per_task?: number;
  geography?: string;
}

export interface ManifestPayload {
  agent_id: string;
  version: number;
  allowed_tools: string[];
  constraints: Constraints;
  issued_at: string;
  expires_at: string | null;
  signature: string;
}

export interface ManifestOut {
  agent_id: string;
  version: number;
  manifest: ManifestPayload;
  issued_at: string;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface TokenOut {
  id: string;
  agent_id: string;
  connector: string;
  scopes: string[];
  issued_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface TrustComponents {
  recent_failure_rate: number;
  regression_pass_rate: number;
  scope_violation_penalty: number;
  history_factor: number;
  composite: number;
  cap_inr?: number;
  seeded?: boolean;
}

export interface TrustOut {
  agent_id: string;
  score: number;
  band: string;
  components: TrustComponents;
  computed_at: string | null;
  trigger_run_id: string | null;
}

export type IncidentKind = "scope_violation" | "spend_breach" | "failure";

export interface Classification {
  failure_class: string | null;
  culprit_span_id: string | null;
  diagnosis: string | null;
  model: string | null;
  backend: string | null;
}

export interface CausationTag {
  tag: "intent_drift" | "sponsored" | "stale_data";
  summary: string;
  span_ids: string[];
}

export interface DataFinding {
  kind: "stale_doc" | "contradiction";
  span_ids: string[];
  action: string;
  doc_id?: string;
  doc_updated_at?: string;
  source_version?: number;
  live_schedule_version?: number;
  fact?: string;
  document_value?: string;
  live_value?: string;
}

export interface Beat {
  kind: string;
  title: string;
  span_id: string;
  facts: Record<string, unknown>;
  caption: string;
  caption_source: string;
  screenshot_sha256?: string | null;
  screenshot_span_id?: string | null;
}

export interface Walkthrough {
  beats: Beat[];
  generated_at: string;
  captions_by_model: number;
  note: string | null;
}

export interface BoxAnnotation {
  span_id: string;
  sha256: string;
  model: string;
  prompt: string;
  boxes: { x1: number; y1: number; x2: number; y2: number; w: number; h: number }[];
}

export interface IncidentDetails {
  classification?: Classification | null;
  causation?: CausationTag[];
  data_findings?: DataFinding[];
  culprit_span_id?: string | null;
  walkthrough?: Walkthrough | null;
  annotations?: BoxAnnotation[];
  assets?: string[];
  notes?: string[];
}

export interface IncidentOut {
  id: string;
  run_id: string;
  agent_id: string | null;
  kind: IncidentKind;
  severity: string;
  culprit_span_id: string | null;
  status: string;
  details: IncidentDetails;
  share_token: string | null;
  created_at: string | null;
}

export interface EvidenceRef {
  span_id: string;
  hash: string;
  role: string;
}

export interface TimelineItem {
  at: string | null;
  span_id: string;
  type: string;
  name: string;
  summary: string;
}

export interface Packet {
  type: "dispute" | "claim";
  simulated: boolean;
  incident_id: string;
  run_id: string;
  agent_id: string | null;
  principal_intent: { text: string; span_id: string };
  scope_manifest_hash: string | null;
  transaction: { merchant: string; flight: string; amount_inr: number; booking_ref: string };
  discrepancy: { expected: string; actual: string };
  evidence: EvidenceRef[];
  timeline: TimelineItem[];
  causation: CausationTag[];
  requested_remedy?: string;
  trace_hash: string;
  replay_url: string;
  narrative?: string;
  dispute_narrative?: string;
  policy?: {
    coverage_limit: number;
    deductible: number;
    base_rate: number;
    trust_band: string;
    trust_score: number | null;
    band_multiplier: number;
    premium_inr: number;
  };
  loss?: { amount_inr: number; deductible_inr: number; payable_inr: number };
}

export interface FilingOut {
  type: "dispute" | "claim";
  packet: Packet;
  trace_hash: string;
  simulated: boolean;
  created_at: string | null;
}

export interface AssertionCheck {
  path: string;
  op: string;
  description?: string;
  start?: string;
  end?: string;
  value?: unknown;
}

export interface CaseResult {
  agent_version: string | null;
  trials: number;
  passes: number;
  verdict: string;
  judged_at: string | null;
}

export interface CaseSummary {
  title: string;
  status: string;
  priority: string;
  entrypoint: string;
  assertion_spec: { output_checks?: AssertionCheck[]; rationale?: string } | null;
  results: CaseResult[];
}

export interface RegressionCaseOut {
  id: string;
  title: string;
  status: string;
  priority: string;
  entrypoint: string;
  assertion_spec: CaseSummary["assertion_spec"];
}

export interface TestResultOut extends CaseResult {
  id: string;
  pass_rate: number;
  details: { trial: number; passed: boolean; error: string | null }[];
}

export interface GeneratedTest {
  case_id: string;
  fixture_filename: string;
  fixture_source: string;
  test_filename: string;
  test_source: string;
}

export interface ModelRunOut {
  id: string;
  source_run_id: string;
  span_id: string;
  model: string;
  output: { task_class?: string; flight?: string | null; reason?: string; error?: string } | null;
  verdict: string | null;
  cost_usd: number | null;
  created_at: string | null;
}

export interface PublicIncident {
  incident: {
    id: string;
    kind: IncidentKind;
    severity: string;
    status: string;
    details: IncidentDetails;
    created_at: string;
  };
  agent: { id: string; name: string } | null;
  run: { id: string; status: string; started_at: string; agent_version: string | null } | null;
  filings: FilingOut[];
  case: CaseSummary | null;
}

const enc = encodeURIComponent;

export const getAgents = (scope: ViewerScope) => ingestFetch<AgentOut[]>("/v1/agents", scope);

export async function getAgent(scope: ViewerScope, id: string): Promise<AgentOut | null> {
  try {
    return await ingestFetch<AgentOut>(`/v1/agents/${enc(id)}`, scope);
  } catch (err) {
    if (err instanceof NotFoundError) return null;
    throw err;
  }
}

export const getManifests = (scope: ViewerScope, id: string) =>
  ingestFetch<ManifestOut[]>(`/v1/agents/${enc(id)}/manifests`, scope);

export const getTokens = (scope: ViewerScope, id: string) =>
  ingestFetch<TokenOut[]>(`/v1/agents/${enc(id)}/tokens`, scope);

export const getTrustHistory = (scope: ViewerScope, id: string, limit = 50) =>
  ingestFetch<TrustOut[]>(`/v1/agents/${enc(id)}/trust/history?limit=${limit}`, scope);

export function getIncidents(
  scope: ViewerScope,
  filter: { agentId?: string; runId?: string; status?: string; limit?: number } = {}
) {
  const params = new URLSearchParams({ limit: String(filter.limit ?? 50) });
  if (filter.agentId) params.set("agent_id", filter.agentId);
  if (filter.runId) params.set("run_id", filter.runId);
  if (filter.status) params.set("status", filter.status);
  return ingestFetch<IncidentOut[]>(`/v1/incidents?${params}`, scope);
}

export async function getIncident(scope: ViewerScope, id: string): Promise<IncidentOut | null> {
  try {
    return await ingestFetch<IncidentOut>(`/v1/incidents/${enc(id)}`, scope);
  } catch (err) {
    if (err instanceof NotFoundError) return null;
    throw err;
  }
}

export const getFilings = (scope: ViewerScope, incidentId: string) =>
  ingestFetch<FilingOut[]>(`/v1/incidents/${enc(incidentId)}/filings`, scope);

export async function getCaseForIncident(scope: ViewerScope, incidentId: string) {
  const data = await ingestFetch<{ cases: RegressionCaseOut[] }>(
    `/v1/regression-cases?incident_id=${enc(incidentId)}&limit=1`,
    scope
  );
  return data.cases[0] ?? null;
}

export async function getCaseResults(scope: ViewerScope, caseId: string) {
  const data = await ingestFetch<{ results: TestResultOut[] }>(
    `/v1/regression-cases/${enc(caseId)}/results`,
    scope
  );
  return data.results;
}

export const getGeneratedTest = (scope: ViewerScope, caseId: string) =>
  ingestFetch<GeneratedTest>(`/v1/regression-cases/${enc(caseId)}/generated-test`, scope);

export const getModelRuns = (scope: ViewerScope) =>
  ingestFetch<ModelRunOut[]>("/v1/model-runs?limit=2000", scope);

export const enableShare = (scope: ViewerScope, id: string) =>
  ingestWrite<{ share_token: string | null }>(`/v1/incidents/${enc(id)}/share`, scope);

export const disableShare = (scope: ViewerScope, id: string) =>
  ingestWrite<{ share_token: string | null }>(`/v1/incidents/${enc(id)}/share`, scope, undefined, "DELETE");

export const resolveIncident = (scope: ViewerScope, id: string) =>
  ingestWrite<IncidentOut>(`/v1/incidents/${enc(id)}/resolve`, scope);

export async function getPublicIncident(token: string): Promise<PublicIncident | null> {
  try {
    return await ingestFetchPublic<PublicIncident>(`/v1/public/incidents/${enc(token)}`);
  } catch (err) {
    if (err instanceof NotFoundError) return null;
    throw err;
  }
}

export const getBlob = (scope: ViewerScope, sha: string) => ingestFetchBinary(`/v1/blobs/${enc(sha)}`, scope);

export const getPublicBlob = (token: string, sha: string) =>
  ingestFetchBinary(`/v1/public/incidents/${enc(token)}/blobs/${enc(sha)}`, null);
