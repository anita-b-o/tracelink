"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api } from "@/lib/api/client";

export function NewInvestigationForm() {
  const router = useRouter();
  const [title, setTitle] = useState(""); const [query, setQuery] = useState(""); const [autoStart, setAutoStart] = useState(true); const [localError, setLocalError] = useState("");
  const mutation = useMutation({ mutationFn: async () => { const normalized = query.trim(); const created = await api.createInvestigation({ title: title.trim() || normalized.replace(/\s+/g, " ").slice(0, 80), original_query: normalized }); if (autoStart) await api.startInvestigation(created.id); return created; }, onSuccess: (item) => router.push(`/investigations/${item.id}`) });
  const submit = (event: FormEvent) => { event.preventDefault(); const normalized = query.trim(); if (!normalized) return setLocalError("Original query is required."); if (normalized.length > 2000) return setLocalError("Original query must be 2,000 characters or fewer."); setLocalError(""); mutation.mutate(); };
  return <main className="narrow-shell"><Link href="/" className="back-link"><ArrowLeft size={16} /> Investigations</Link><section className="form-panel"><div className="form-icon"><Search /></div><p className="eyebrow">New case</p><h1>New investigation</h1><p>Describe the subject or question. TraceLink will plan the research workflow and preserve every source.</p><form onSubmit={submit} noValidate><label>Title <span>Optional</span><input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} placeholder="Acme corporate profile" /></label><label>Original query <span>{query.length}/2000</span><textarea value={query} onChange={(e) => setQuery(e.target.value)} maxLength={2000} rows={8} placeholder="Investigate the ownership, directors, domains, and related organizations for…" required /></label><label className="check-label"><input type="checkbox" checked={autoStart} onChange={(e) => setAutoStart(e.target.checked)} /><span><strong>Start automatically</strong><small>Queue research tasks immediately after creation.</small></span></label>{(localError || mutation.error) && <div className="inline-error" role="alert">{localError || mutation.error?.message}</div>}<button className="button wide" disabled={mutation.isPending}>{mutation.isPending ? "Creating…" : <>Create investigation <ArrowRight size={17} /></>}</button></form></section></main>;
}
