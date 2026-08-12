"use client";

import Link from "next/link";
import { Network } from "lucide-react";
import { usePathname } from "next/navigation";

import { useAuth } from "@/components/auth-provider";

export function AppHeader() {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  if (["/login", "/register"].includes(pathname)) return null;
  return <header className="app-bar">
    <Link href="/" className="brand"><span className="brand-mark"><Network size={18} /></span><span>TraceLink</span></Link>
    <nav aria-label="Primary navigation"><span className="session-user">{user?.display_name ?? user?.email}</span><Link href="/">Investigations</Link><Link href="/investigations/new" className="button small">New investigation</Link><button className="button secondary small" onClick={() => void logout()}>Log out</button></nav>
  </header>;
}
