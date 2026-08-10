"use client";

import { useEffect, useState } from "react";

type Availability = "checking" | "available" | "unavailable";

const labels: Record<Availability, string> = {
  checking: "Comprobando servicios…",
  available: "API, PostgreSQL y Redis disponibles",
  unavailable: "Servicios aún no disponibles",
};

export function ServiceStatus() {
  const [availability, setAvailability] = useState<Availability>("checking");

  useEffect(() => {
    const controller = new AbortController();
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

    async function checkServices() {
      try {
        const response = await fetch(`${apiUrl}/api/health/ready`, {
          signal: controller.signal,
        });
        setAvailability(response.ok ? "available" : "unavailable");
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setAvailability("unavailable");
        }
      }
    }

    void checkServices();
    return () => controller.abort();
  }, []);

  return (
    <div
      className="inline-flex items-center gap-3 rounded-full border border-[var(--surface-border)] bg-[var(--surface)] px-4 py-2 text-sm text-[var(--muted)]"
      role="status"
    >
      <span
        aria-hidden="true"
        className={`size-2 rounded-full ${
          availability === "available"
            ? "bg-[var(--accent)]"
            : availability === "checking"
              ? "animate-pulse bg-amber-300"
              : "bg-rose-400"
        }`}
      />
      {labels[availability]}
    </div>
  );
}
