import type { Progress as ProgressType } from "@/lib/api/types";

export function Progress({ value, compact = false }: { value: ProgressType; compact?: boolean }) {
  return <div className="progress-block" aria-label={`${value.percent}% complete`}><div className="progress-track"><span style={{ width: `${value.percent}%` }} /></div><div className="progress-meta"><strong>{value.percent}%</strong>{!compact && <span>{value.completed}/{value.total} tasks · {value.failed} failed</span>}</div></div>;
}
