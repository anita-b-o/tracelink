import { AlertTriangle, Inbox, LoaderCircle, RotateCcw } from "lucide-react";

export function LoadingState({ label = "Loading…" }: { label?: string }) { return <div className="state-panel" role="status"><LoaderCircle className="spin" aria-hidden="true" /><p>{label}</p></div>; }
export function EmptyState({ title, detail }: { title: string; detail: string }) { return <div className="state-panel"><Inbox aria-hidden="true" /><h3>{title}</h3><p>{detail}</p></div>; }
export function ErrorState({ error, retry }: { error: Error; retry: () => void }) { return <div className="state-panel state-error" role="alert"><AlertTriangle aria-hidden="true" /><h3>Unable to load this view</h3><p>{error.message}</p><button className="button secondary" onClick={retry}><RotateCcw size={15} /> Retry</button></div>; }
