const tone: Record<string, string> = { COMPLETED: "success", CONFIRMED: "success", ACCEPTED: "success", AUTO_ACCEPTED: "success", AUTO_MATCHED: "success", RUNNING: "info", PENDING: "warning", DRAFT: "neutral", POSSIBLE: "warning", PROBABLE: "info", PARTIAL: "warning", FAILED: "danger", REJECTED: "danger", CANCELLED: "neutral", CONTRADICTED: "danger" };

export function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge status-${tone[status] ?? "neutral"}`}>{status.replaceAll("_", " ")}</span>;
}
