import { Suspense } from "react";

import { LoadingState } from "@/components/ui/async-state";
import { Dashboard } from "@/features/investigations/dashboard";

export default function Home() { return <Suspense fallback={<main className="dashboard-shell"><LoadingState label="Loading investigations…" /></main>}><Dashboard /></Suspense>; }
