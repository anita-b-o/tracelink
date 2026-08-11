import type { Answer, DocumentDetail, DocumentSummary, Entity, EntityCandidate, Evidence, GraphData, Investigation, Mention, Progress, Relationship, RelationshipCandidate, RelationshipDetail, Report, ReportSummary, ReportType, SearchHit, Source, Task } from "./types";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
const DEFAULT_TIMEOUT_MS = 15_000;

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

export async function apiRequest<T>(path: string, init: RequestInit = {}, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort("timeout"), timeoutMs);
  try {
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers: { "Content-Type": "application/json", ...init.headers }, signal: controller.signal });
    } catch {
      if (controller.signal.aborted) throw new ApiError(`The TraceLink API did not respond within ${Math.round(timeoutMs / 1000)} seconds.`, null, "timeout");
      throw new ApiError(`Cannot reach the TraceLink API at ${API_BASE_URL}.`, null, "network");
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
