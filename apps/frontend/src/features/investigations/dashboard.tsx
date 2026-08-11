"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CalendarDays, FileSearch, Link2, Plus, Users } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { EmptyState, ErrorState, LoadingState } from "@/components/ui/async-state";
import { Progress } from "@/components/ui/progress";
import { StatusBadge } from "@/components/ui/status-badge";
import { api } from "@/lib/api/client";

const PAGE_SIZE = 12;

export function Dashboard() {
  const searchParams = useSearchParams();
  const page = Math.max(Number(searchParams.get("page") ?? "1") || 1, 1);
  const query = useQuery({ queryKey: ["investigations", page], queryFn: () => api.investigations(PAGE_SIZE + 1, (page - 1) * PAGE_SIZE) });
  const items = query.data?.slice(0, PAGE_SIZE) ?? [];
  const hasNext = (query.data?.length ?? 0) > PAGE_SIZE;
  return <main className="page-shell">
    <section className="page-heading"><div><p className="eyebrow">Investigation workspace</p><h1>Investigations</h1><p>Evidence-first research, grounded claims, and traceable decisions.</p></div><Link href="/investigations/new" className="button"><Plus size={17} /> New investigation</Link></section>
    {query.isLoading ? <LoadingState label="Loading investigations…" /> : query.error ? <ErrorState error={query.error} retry={() => void query.refetch()} /> : items.length === 0 ? <EmptyState title="No investigations yet" detail="Create an investigation to start collecting and reviewing evidence." /> : <>
      <section className="investigation-grid" aria-label="Investigations">
        {items.map((item) => <article className="investigation-card" key={item.id}>
          <div className="card-top"><StatusBadge status={item.status} /><time dateTime={item.created_at}><CalendarDays size={14} /> {new Date(item.created_at).toLocaleDateString()}</time></div>
          <h2><Link href={`/investigations/${item.id}`}>{item.title}</Link></h2><p className="clamp-2">{item.original_query}</p><Progress value={item.progress} />
          <dl className="count-strip"><div><dt><Users /> Entities</dt><dd>{item.counts.entities}</dd></div><div><dt><Link2 /> Relations</dt><dd>{item.counts.relationships}</dd></div><div><dt><FileSearch /> Sources</dt><dd>{item.counts.sources}</dd></div></dl>
          <Link className="card-link" href={`/investigations/${item.id}`}>Open workspace <ArrowRight size={15} /></Link>
        </article>)}
      </section>
      <nav className="pagination" aria-label="Investigations pages">{page > 1 && <Link className="button secondary" href={`/?page=${page - 1}`}>Previous</Link>}<span>Page {page}</span>{hasNext && <Link className="button secondary" href={`/?page=${page + 1}`}>Next</Link>}</nav>
    </>}
  </main>;
}
