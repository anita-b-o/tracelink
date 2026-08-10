import { ServiceStatus } from "@/components/service-status";

const foundations = [
  ["Frontend", "Next.js, React, TypeScript y Tailwind"],
  ["Backend", "FastAPI, PostgreSQL, Redis y Celery"],
  ["Principio", "Investigación basada en evidencia verificable"],
] as const;

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col justify-center px-6 py-20 lg:px-12">
      <ServiceStatus />
      <p className="mt-12 text-sm font-semibold uppercase tracking-[0.28em] text-[var(--accent)]">
        TraceLink · Fase 0
      </p>
      <h1 className="mt-4 max-w-4xl text-5xl font-semibold tracking-tight sm:text-7xl">
        Investigación OSINT con evidencia, contexto y trazabilidad.
      </h1>
      <p className="mt-7 max-w-2xl text-lg leading-8 text-[var(--muted)]">
        El entorno base está listo. Las capacidades de investigación se incorporarán de forma
        incremental a partir de la Fase 1.
      </p>
      <section className="mt-14 grid gap-4 md:grid-cols-3" aria-label="Fundaciones técnicas">
        {foundations.map(([title, description]) => (
          <article
            className="rounded-2xl border border-[var(--surface-border)] bg-[color:var(--surface)]/80 p-6"
            key={title}
          >
            <h2 className="font-semibold">{title}</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--muted)]">{description}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
