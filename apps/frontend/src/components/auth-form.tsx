"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { apiRequest } from "@/lib/api/client";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const { reload } = useAuth();
  const expired = useSearchParams().get("session_expired");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setPending(true); setError(null);
    const data = new FormData(event.currentTarget);
    const body = { email: String(data.get("email")), password: String(data.get("password")), ...(mode === "register" ? { display_name: String(data.get("display_name") || "") || null } : {}) };
    try { await apiRequest(`/api/auth/${mode}`, { method: "POST", body: JSON.stringify(body) }, 15_000, false); await reload(); }
    catch (value) { setError(value instanceof Error ? value.message : "Authentication failed."); setPending(false); }
  }
  return <main className="auth-shell"><form className="auth-card" onSubmit={submit}>
    <h1>{mode === "login" ? "Sign in" : "Create account"}</h1>
    <p>{mode === "login" ? "Continue to your investigation workspace." : "Use at least 12 characters for your password."}</p>
    {expired && <div className="warning-banner">Your session expired. Sign in to continue.</div>}
    {mode === "register" && <label>Display name<input name="display_name" maxLength={100} autoComplete="name" /></label>}
    <label>Email<input name="email" type="email" maxLength={320} required autoComplete="email" /></label>
    <label>Password<input name="password" type="password" minLength={mode === "register" ? 12 : 1} maxLength={128} required autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
    {error && <div className="inline-error" role="alert">{error}</div>}
    <button className="button" disabled={pending}>{pending ? "Please wait…" : mode === "login" ? "Sign in" : "Register"}</button>
    <Link href={mode === "login" ? "/register" : "/login"}>{mode === "login" ? "Create an account" : "Already have an account?"}</Link>
  </form></main>;
}
