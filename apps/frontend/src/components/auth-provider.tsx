"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ApiError, apiRequest } from "@/lib/api/client";

export type AuthUser = { id: string; email: string; display_name: string | null; is_active: boolean };
type AuthContextValue = { user: AuthUser | null; loading: boolean; reload: () => Promise<void>; logout: () => Promise<void> };
const AuthContext = createContext<AuthContextValue | null>(null);
const PUBLIC_PATHS = new Set(["/login", "/register"]);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const pathname = usePathname();
  const search = useSearchParams();
  const router = useRouter();
  const reload = useCallback(async () => {
    setLoading(true);
    try { setUser(await apiRequest<AuthUser>("/api/auth/me", {}, 8_000, false)); }
    catch (error) { if (error instanceof ApiError && error.status === 401) setUser(null); else throw error; }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    let active = true;
    void apiRequest<AuthUser>("/api/auth/me", {}, 8_000, false)
      .then((value) => { if (active) setUser(value); })
      .catch((error: unknown) => {
        if (active && error instanceof ApiError && error.status === 401) setUser(null);
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    const expired = () => { setUser(null); router.replace("/login?session_expired=1"); };
    window.addEventListener("tracelink:session-expired", expired);
    return () => window.removeEventListener("tracelink:session-expired", expired);
  }, [router]);
  useEffect(() => {
    if (!loading && !user && !PUBLIC_PATHS.has(pathname)) {
      const reason = search.get("session_expired") ? "?session_expired=1" : "";
      router.replace(`/login${reason}`);
    }
    if (!loading && user && PUBLIC_PATHS.has(pathname)) router.replace("/");
  }, [loading, pathname, router, search, user]);
  const logout = useCallback(async () => {
    await apiRequest("/api/auth/logout", { method: "POST" }, 8_000, false);
    setUser(null);
    router.replace("/login");
  }, [router]);
  const value = useMemo(() => ({ user, loading, reload, logout }), [user, loading, reload, logout]);
  const publicRoute = PUBLIC_PATHS.has(pathname);
  return <AuthContext.Provider value={value}>{(publicRoute || (!loading && user)) ? children : <main className="auth-shell"><p>Checking session…</p></main>}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
