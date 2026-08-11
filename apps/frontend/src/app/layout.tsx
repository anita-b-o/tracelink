import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";
import { Network } from "lucide-react";

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
          <header className="app-bar">
            <Link href="/" className="brand"><span className="brand-mark"><Network size={18} /></span><span>TraceLink</span></Link>
            <nav aria-label="Primary navigation"><Link href="/">Investigations</Link><Link href="/investigations/new" className="button small">New investigation</Link></nav>
          </header>
          {children}
        </QueryProvider>
      </body>
    </html>
  );
}
