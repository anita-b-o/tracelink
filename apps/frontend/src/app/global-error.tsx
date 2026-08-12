"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

export default function GlobalError({ error }: { error: Error & { digest?: string } }) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);
  return (
    <html lang="en">
      <body>
        <main className="auth-shell">
          <div className="auth-card">
            <h1>TraceLink is temporarily unavailable</h1>
            <p>Reload the page or try again shortly.</p>
            <button onClick={() => location.reload()}>Reload</button>
          </div>
        </main>
      </body>
    </html>
  );
}
