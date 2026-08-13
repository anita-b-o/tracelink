import type { Answer, DocumentDetail, DocumentSummary, Entity, EntityCandidate, Evidence, GraphData, Investigation, Mention, Progress, Relationship, RelationshipCandidate, RelationshipDetail, Report, ReportSummary, ReportType, SearchHit, Source, Task } from "./types";

type DemoEnvironment = {
  NEXT_PUBLIC_DEMO_MODE?: string;
  NEXT_PUBLIC_VERCEL_DEMO_MODE?: string;
};

export function isDemoEnvironment(
  environment: DemoEnvironment = process.env as DemoEnvironment,
): boolean {
  return environment.NEXT_PUBLIC_DEMO_MODE === "true";
}

export function isVercelDemoEnvironment(
  environment: DemoEnvironment = process.env as DemoEnvironment,
): boolean {
  return environment.NEXT_PUBLIC_VERCEL_DEMO_MODE === "true";
}

export function defaultApiTimeoutMs(environment?: DemoEnvironment): number {
  if (isVercelDemoEnvironment(environment)) return 250_000;
  return isDemoEnvironment(environment) ? 90_000 : 15_000;
}

export function timeoutMessage(timeoutMs: number, environment?: DemoEnvironment): string {
  if (isVercelDemoEnvironment(environment)) {
    return `The serverless demo did not finish within ${Math.round(timeoutMs / 1000)} seconds. If an outbox job was already enqueued, it remains durable; refresh the investigation to retry.`;
  }
  if (isDemoEnvironment(environment)) {
    return `The free demo API may still be waking up after ${Math.round(timeoutMs / 1000)} seconds. Wait a moment and retry.`;
  }
  return `The TraceLink API did not respond within ${Math.round(timeoutMs / 1000)} seconds.`;
}

let refreshPromise: Promise<boolean> | null = null;

function cookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  const item = document.cookie.split("; ").find((value) => value.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : null;
}

async function csrfToken(): Promise<string> {
  const existing = cookie("tracelink_csrf");
  if (existing) return existing;
  const response = await fetch("/api/auth/csrf", { credentials: "same-origin", cache: "no-store" });
  if (!response.ok) throw new ApiError("Could not initialize a secure session.", response.status, "http");
  const payload = await response.json() as { csrf_token: string };
  return payload.csrf_token;
}

async function refreshSession(): Promise<boolean> {
  if (!refreshPromise) refreshPromise = (async () => {
    try {
      const csrf = await csrfToken();
      const response = await fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": csrf } });
      return response.ok;
    } catch { return false; }
    finally { refreshPromise = null; }
  })();
  return refreshPromise;
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number | null, public readonly kind: "http" | "network" | "timeout" | "malformed", public readonly fieldErrors: string[] = []) {
    super(message);
    this.name = "ApiError";
  }
}

function validationMessages(detail: unknown): string[] {
  if (!Array.isArray(detail)) return [];
  return detail.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const value = item as { loc?: unknown[]; msg?: unknown };
    const field = value.loc?.slice(1).join(".");
    return typeof value.msg === "string" ? [`${field ? `${field}: ` : ""}${value.msg}`] : [];
  });
}

export async function apiRequest<T>(path: string, init: RequestInit = {}, timeoutMs = defaultApiTimeoutMs(), allowRefresh = true): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort("timeout"), timeoutMs);
  try {
    let response: Response;
    try {
      const headers = new Headers(init.headers);
      if (init.body) headers.set("Content-Type", "application/json");
      if (init.method && !["GET", "HEAD"].includes(init.method.toUpperCase())) headers.set("X-CSRF-Token", await csrfToken());
      response = await fetch(path, { ...init, credentials: "same-origin", headers, signal: controller.signal });
    } catch {
      if (controller.signal.aborted) throw new ApiError(timeoutMessage(timeoutMs), null, "timeout");
      throw new ApiError("Cannot reach the TraceLink API.", null, "network");
    }
    if (response.status === 401 && allowRefresh && !path.startsWith("/api/auth/")) {
      if (await refreshSession()) return apiRequest<T>(path, init, timeoutMs, false);
      if (typeof window !== "undefined") window.dispatchEvent(new Event("tracelink:session-expired"));
      throw new ApiError("Your session expired. Sign in again; the operation was not saved.", 401, "http");
    }
    let payload: unknown = null;
    if (response.status !== 204) {
      try { payload = await response.json(); }
      catch { throw new ApiError(`The API returned an unreadable response for ${path}.`, response.status, "malformed"); }
    }
    if (!response.ok) {
      const body = payload as { detail?: unknown } | null;
      const fields = validationMessages(body?.detail);
      const detail = typeof body?.detail === "string" ? body.detail : fields.join("; ");
      const label = response.status === 404 ? "Not found" : response.status === 409 ? "Conflict" : response.status === 422 ? "Validation failed" : `API error ${response.status}`;
      throw new ApiError(`${label}${detail ? `: ${detail}` : ` while requesting ${path}`}.`, response.status, "http", fields);
    }
    return payload as T;
  } finally { clearTimeout(timeout); }
}

const params = (values: Record<string, string | number | undefined | null>) => {
  const search = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== "") search.set(key, String(value)); });
  return search.size ? `?${search}` : "";
};

export const api = {
  investigations: (limit = 26, offset = 0) => apiRequest<Investigation[]>(`/api/investigations${params({ limit, offset })}`),
  investigation: (id: string) => apiRequest<Investigation>(`/api/investigations/${id}`),
  createInvestigation: (body: { title: string; original_query: string }) => apiRequest<Investigation>("/api/investigations", { method: "POST", body: JSON.stringify(body) }),
  startInvestigation: (id: string) => apiRequest<Investigation>(`/api/investigations/${id}/start`, { method: "POST" }),
  cancelInvestigation: (id: string) => apiRequest<Investigation>(`/api/investigations/${id}/cancel`, { method: "POST" }),
  progress: (id: string) => apiRequest<Progress>(`/api/investigations/${id}/progress`),
  tasks: (id: string) => apiRequest<Task[]>(`/api/investigations/${id}/tasks`),
  retryTask: (id: string) => apiRequest<Task>(`/api/research-tasks/${id}/retry`, { method: "POST" }),
  entities: (id: string, query: Record<string, string | number | undefined>) => apiRequest<Entity[]>(`/api/investigations/${id}/entities${params(query)}`),
  mentions: (id: string, query: Record<string, string | number | undefined>) => apiRequest<Mention[]>(`/api/investigations/${id}/entity-mentions${params(query)}`),
  entityEvidence: (id: string, entityId: string) => apiRequest<Evidence[]>(`/api/investigations/${id}/entities/${entityId}/evidence${params({limit:100})}`),
  entityCandidates: (id: string, query: Record<string, string | number | undefined>) => apiRequest<EntityCandidate[]>(`/api/investigations/${id}/resolution-candidates${params(query)}`),
  relationships: (id: string, query: Record<string, string | number | undefined>) => apiRequest<Relationship[]>(`/api/investigations/${id}/relationships${params(query)}`),
  relationship: (id: string, relationshipId: string) => apiRequest<RelationshipDetail>(`/api/investigations/${id}/relationships/${relationshipId}`),
  relationshipCandidates: (id: string, query: Record<string, string | number | undefined>) => apiRequest<RelationshipCandidate[]>(`/api/investigations/${id}/relationship-candidates${params(query)}`),
  sources: (id: string, query: Record<string, string | number | undefined>) => apiRequest<Source[]>(`/api/investigations/${id}/sources${params(query)}`),
  documents: (id: string, query: Record<string, string | number | undefined>) => apiRequest<DocumentSummary[]>(`/api/investigations/${id}/documents${params(query)}`),
  document: (id: string, contentOffset = 0) => apiRequest<DocumentDetail>(`/api/documents/${id}${params({ content_offset: contentOffset, content_limit: 5000 })}`),
  evidence: (id: string) => apiRequest<Evidence>(`/api/evidence/${id}`),
  graph: (id: string, query: Record<string, string | number | undefined>) => apiRequest<GraphData>(`/api/investigations/${id}/graph${params(query)}`),
  ask: (id: string, question: string) => apiRequest<Answer>(`/api/investigations/${id}/ask`, { method: "POST", body: JSON.stringify({ question }) }),
  search: (id: string, query: string) => apiRequest<SearchHit[]>(`/api/investigations/${id}/search`, { method: "POST", body: JSON.stringify({ query, top_k: 10, filters: {} }) }),
  reports: (id: string) => apiRequest<ReportSummary[]>(`/api/investigations/${id}/reports`),
  report: (id: string) => apiRequest<Report>(`/api/reports/${id}`),
  createReport: (id: string, type: ReportType, subjectEntityId?: string) => apiRequest<ReportSummary>(`/api/investigations/${id}/reports`, { method: "POST", body: JSON.stringify({ type, subject_entity_id: subjectEntityId || null }) }),
  reviewEntity: (id: string, decision: "accept" | "reject") => apiRequest(`/api/entity-resolution-candidates/${id}/${decision}`, { method: "POST" }),
  reviewRelationship: (id: string, decision: "accept" | "reject") => apiRequest(`/api/relationship-candidates/${id}/${decision}`, { method: "POST" }),
};
