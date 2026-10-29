import type { DocumentStatus, EvidenceStatus } from "@/lib/api/types";

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const map: Record<DocumentStatus, { cls: string; label: string }> = {
    queued: { cls: "idle", label: "Queued" },
    processing: { cls: "warn", label: "Indexing" },
    ready: { cls: "ok", label: "Ready" },
    failed: { cls: "err", label: "Failed" },
  };
  const item = map[status];
  return <span className={`badge ${item.cls}`}>{item.label}</span>;
}

export function EvidenceBadge({
  enough,
  status,
}: {
  enough: boolean;
  status: EvidenceStatus;
}) {
  if (status === "unverified") {
    return <span className="badge warn">Answer withheld — missing citation</span>;
  }
  if (!enough || status === "absent") {
    return <span className="badge err">Not in this PDF</span>;
  }
  if (status === "nearby_only") {
    return <span className="badge warn">Related passage only</span>;
  }
  return <span className="badge ok">Cited passage</span>;
}
