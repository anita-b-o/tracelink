"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";

import { EmptyState, ErrorState, LoadingState } from "@/components/ui/async-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api/client";

const statuses = ["PENDING", "ACCEPTED", "REJECTED", "AUTO_MATCHED", "AUTO_ACCEPTED", "CONTRADICTED"];
const entityStatuses = new Set(["PENDING", "ACCEPTED", "REJECTED", "AUTO_MATCHED"]);
const relationshipStatuses = new Set(["PENDING", "ACCEPTED", "REJECTED", "AUTO_ACCEPTED", "CONTRADICTED"]);

export function ReviewView({ id }: { id: string }) {
  const search = useSearchParams();
  const router = useRouter();
  const status = search.get("review_status") ?? "PENDING";
  const showEntities = entityStatuses.has(status);
  const showRelationships = relationshipStatuses.has(status);
  const client = useQueryClient();
  const entities = useQuery({
    queryKey: ["entity-candidates", id, status],
    queryFn: () => api.entityCandidates(id, { candidate_status: status, limit: 100 }),
    enabled: showEntities,
  });
  const relationships = useQuery({
    queryKey: ["relationship-candidates", id, status],
    queryFn: () => api.relationshipCandidates(id, { candidate_status: status, limit: 100 }),
    enabled: showRelationships,
  });
  const invalidate = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["entity-candidates", id] }),
      client.invalidateQueries({ queryKey: ["relationship-candidates", id] }),
      client.invalidateQueries({ queryKey: ["entities", id] }),
      client.invalidateQueries({ queryKey: ["relationships", id] }),
      client.invalidateQueries({ queryKey: ["graph", id] }),
      client.invalidateQueries({ queryKey: ["investigation", id] }),
    ]);
  const entityReview = useMutation({
    mutationFn: ({ candidate, decision }: { candidate: string; decision: "accept" | "reject" }) => api.reviewEntity(candidate, decision),
    onSuccess: invalidate,
  });
  const relationshipReview = useMutation({
    mutationFn: ({ candidate, decision }: { candidate: string; decision: "accept" | "reject" }) => api.reviewRelationship(candidate, decision),
    onSuccess: invalidate,
  });
  const loading = (showEntities && entities.isLoading) || (showRelationships && relationships.isLoading);
  const error = entities.error || relationships.error;

  if (loading) return <LoadingState label="Loading review queue…" />;
  if (error) return <ErrorState error={error} retry={() => { void entities.refetch(); void relationships.refetch(); }} />;

  const changeStatus = (value: string) => {
    const next = new URLSearchParams(search);
    next.set("review_status", value);
    router.push(`?${next}`);
  };

  return <>
    <div className="section-heading">
      <div><h2>Human review</h2><p>Candidate-scoped decisions preserve provenance and backend invariants.</p></div>
      <div className="filter-row">
        <select aria-label="Review status" value={status} onChange={(event) => changeStatus(event.target.value)}>
          {statuses.map((value) => <option key={value}>{value}</option>)}
        </select>
      </div>
    </div>
    {entityReview.error && <div className="inline-error">{entityReview.error.message}</div>}
    {relationshipReview.error && <div className="inline-error">{relationshipReview.error.message}</div>}
    <div className="review-grid">
      <section>
        <div className="panel-header"><h3>Entity resolution</h3><StatusBadge status={`${entities.data?.length ?? 0} CANDIDATES`} /></div>
        {!entities.data?.length ? <EmptyState title="No entity candidates" detail={`There are no ${status.toLowerCase()} entity resolution candidates.`} /> :
          <div className="list-stack">{entities.data.map((item) =>
            <article className="candidate-card" key={item.id}>
              <header><div><h3>{item.provisional_entity?.canonical_name ?? item.mention.surface_form}</h3><p>Possible match → <strong>{item.candidate_entity.canonical_name}</strong></p></div><StatusBadge status={item.status} /></header>
              <blockquote>{item.mention.context_preview}</blockquote>
              <div className="detail-grid"><div className="detail-item"><span>Score</span>{Math.round(item.score * 100)}%</div><div className="detail-item"><span>Type</span>{item.candidate_entity.type}</div></div>
              <div className="signal-list">{Object.entries(item.signals).slice(0, 8).map(([key, value]) => <span key={key}>{key}: {String(value)}</span>)}</div>
              {item.status === "PENDING" && <div className="candidate-actions"><button className="button small" disabled={entityReview.isPending} onClick={() => entityReview.mutate({ candidate: item.id, decision: "accept" })}><Check size={14} /> Accept match</button><button className="button danger small" disabled={entityReview.isPending} onClick={() => entityReview.mutate({ candidate: item.id, decision: "reject" })}><X size={14} /> Reject match</button></div>}
            </article>)}</div>}
      </section>
      <section>
        <div className="panel-header"><h3>Relationship candidates</h3><StatusBadge status={`${relationships.data?.length ?? 0} CANDIDATES`} /></div>
        {!relationships.data?.length ? <EmptyState title="No relationship candidates" detail={`There are no ${status.toLowerCase()} relationship candidates.`} /> :
          <div className="list-stack">{relationships.data.map((item) =>
            <article className="candidate-card" key={item.id}>
              <header><div><h3>{item.source_entity.canonical_name} → {item.target_entity.canonical_name}</h3><p>{item.type.replaceAll("_", " ")} · {item.claim_kind}</p></div><StatusBadge status={item.status} /></header>
              <blockquote>{item.evidence_preview ?? "No evidence preview"}</blockquote>
              <div className="detail-grid"><div className="detail-item"><span>Score</span>{Math.round(item.score * 100)}%</div><div className="detail-item"><span>Extraction confidence</span>{Math.round(item.confidence * 100)}%</div><div className="detail-item"><span>Validity</span>{item.temporal_start ?? "—"} – {item.temporal_end ?? "—"}</div><div className="detail-item"><span>Method</span>{item.extraction_method}</div></div>
              <div className="signal-list">{(item.reason_codes ?? []).map((code) => <span key={code}>{code}</span>)}</div>
              {item.status === "PENDING" && <div className="candidate-actions"><button className="button small" disabled={relationshipReview.isPending} onClick={() => relationshipReview.mutate({ candidate: item.id, decision: "accept" })}><Check size={14} /> Accept</button><button className="button danger small" disabled={relationshipReview.isPending} onClick={() => relationshipReview.mutate({ candidate: item.id, decision: "reject" })}><X size={14} /> Reject</button></div>}
            </article>)}</div>}
      </section>
    </div>
  </>;
}
