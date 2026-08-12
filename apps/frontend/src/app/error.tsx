"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);
  return (
    <main className="dashboard-shell">
      <div className="panel">
        <h1>Something went wrong</h1>
        <p>The page could not be loaded. Your last operation may not have been saved.</p>
        <button className="button" onClick={reset}>
          Try again
        </button>
      </div>
    </main>
  );
}
