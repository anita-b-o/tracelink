import type { Metadata } from "next";
import { Suspense, type ReactNode } from "react";

import { AppHeader } from "@/components/app-header";
import { AuthProvider } from "@/components/auth-provider";
import { QueryProvider } from "@/components/query-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "TraceLink",
  description: "Evidence-first OSINT research workspace",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <QueryProvider>
          <Suspense fallback={<main className="auth-shell"><p>Checking session…</p></main>}>
            <AuthProvider>
              <AppHeader />
              {children}
            </AuthProvider>
          </Suspense>
        </QueryProvider>
      </body>
    </html>
  );
}
