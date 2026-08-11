"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CalendarDays, CircleDot, FileText, Link2, Play, RotateCcw, Users } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";

import { ErrorState, LoadingState } from "@/components/ui/async-state";
import { Progress } from "@/components/ui/progress";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api/client";
import { ArtifactsView, EntitiesView, OverviewView, RelationshipsView, TasksView } from "./views";
import { GraphView } from "@/features/graph/graph-view";
import { TimelineView } from "@/features/timeline/timeline-view";
import { AskView } from "@/features/rag/ask-view";
import { ReportsView } from "@/features/reports/reports-view";
import { ReviewView } from "@/features/review/review-view";

const tabs = ["overview", "tasks", "entities", "relationships", "sources", "documents", "timeline", "graph", "ask", "reports", "review"] as const;
type Tab = (typeof tabs)[number];
const activeStatuses = new Set(["PENDING", "RUNNING"]);
export function investigationActions(status:string) { return { start: status === "DRAFT", cancel: ["DRAFT", "PENDING", "RUNNING"].includes(status), retryFailedTasks: ["FAILED", "PARTIAL"].includes(status) }; }

export function InvestigationWorkspace({ id }: { id: string }) {
  const search = useSearchParams(); const router=useRouter(); const client = useQueryClient();
  const requested = search.get("tab")?.toLowerCase(); const tab: Tab = tabs.includes(requested as Tab) ? requested as Tab : "overview";
  const investigation = useQuery({ queryKey: ["investigation", id], queryFn: () => api.investigation(id), refetchInterval: (query) => activeStatuses.has(query.state.data?.status ?? "") ? 3000 : false });
  const mutation = useMutation({ mutationFn: (action: "start" | "cancel") => action === "start" ? api.startInvestigation(id) : api.cancelInvestigation(id), onSuccess: () => { void client.invalidateQueries({ queryKey: ["investigation", id] }); void client.invalidateQueries({ queryKey: ["tasks", id] }); } });
  if (investigation.isLoading) return <main className="workspace-shell"><LoadingState label="Loading investigation workspace…" /></main>;
  if (investigation.error || !investigation.data) return <main className="workspace-shell"><ErrorState error={investigation.error ?? new Error("Investigation not found")} retry={() => void investigation.refetch()} /></main>;
  const item = investigation.data;
  const actions = investigationActions(item.status);
  return <main className="workspace-shell">
    <header className="workspace-header"><div className="workspace-title"><div className="card-top"><StatusBadge status={item.status} /><span className="eyebrow">Investigation</span></div><h1>{item.title}</h1><p><CalendarDays size={13} /> Created {new Date(item.created_at).toLocaleString()}</p></div><Progress value={item.progress} />
      <div className="workspace-actions">{actions.start && <button className="button" disabled={mutation.isPending} onClick={() => mutation.mutate("start")}><Play size={15} /> Start</button>}{actions.cancel && <button className="button danger" disabled={mutation.isPending} onClick={() => mutation.mutate("cancel")}><Ban size={15} /> Cancel</button>}<button className="button secondary" onClick={() => void investigation.refetch()}><RotateCcw size={15} /> Refresh</button></div>
    </header>{mutation.error && <div className="inline-error" role="alert">{mutation.error.message}</div>}
    <nav className="tab-list" aria-label="Investigation workspace">{tabs.map((value) => <button key={value} aria-current={tab===value?"page":undefined} className={tab === value ? "active" : ""} onClick={()=>router.push(`/investigations/${id}?tab=${value}`)}>{value[0].toUpperCase()+value.slice(1)}</button>)}</nav>
    <section className="workspace-view">{tab === "overview" && <OverviewView investigation={item} />}{tab === "tasks" && <TasksView id={id} active={activeStatuses.has(item.status)} />}{tab === "entities" && <EntitiesView id={id} />}{tab === "relationships" && <RelationshipsView id={id} />}{tab === "sources" && <ArtifactsView id={id} kind="sources" />}{tab === "documents" && <ArtifactsView id={id} kind="documents" />}{tab === "timeline" && <TimelineView id={id} />}{tab === "graph" && <GraphView id={id} />}{tab === "ask" && <AskView id={id} />}{tab === "reports" && <ReportsView id={id} />}{tab === "review" && <ReviewView id={id} />}</section>
  </main>;
}

export function MetricGrid({ values }: { values: Array<[string, number, typeof Users]> }) { return <div className="metric-grid">{values.map(([label,value,Icon]) => <div className="metric" key={label}><span className="metric-label"><Icon /> {label}</span><strong>{value}</strong></div>)}</div>; }

export const metricIcons = { tasks: CircleDot, entities: Users, relationships: Link2, sources: FileText, documents: FileText, contradictions: Ban };
