"use client";

import type { Answer, Citation } from "@/lib/api/types";
import { EvidenceBadge } from "@/components/StatusBadge";

export function CitationPanel({
  answer,
  filename,
  selected,
  onSelect,
}: {
  answer: Answer | null;
  filename: string;
  selected: Citation | null;
  onSelect: (citation: Citation) => void;
}) {
  if (!answer) {
    return (
      <div className="empty">
        Cited PDF filename, page number, and supporting excerpt will appear here after you ask.
      </div>
    );
  }
  if (!answer.enough_evidence || answer.citations.length === 0) {
    return (
      <div>
        <EvidenceBadge enough={false} status={answer.evidence_status} />
        <p className="empty">
          No cited passage was returned. A related page is not treated as proof of a document-wide
          absence.
        </p>
      </div>
    );
  }
  return (
    <div className="cite-list">
      {answer.citations.map((citation, index) => {
        const active = selected?.passage_id === citation.passage_id;
        return (
          <button
            key={citation.passage_id}
            type="button"
            className={`cite-card ${active ? "active" : ""}`}
            aria-pressed={active}
            onClick={() => onSelect(citation)}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
              <strong>
                {filename} · p. {citation.pdf_page}
              </strong>
              <span>
                {index + 1}/{answer.citations.length}
              </span>
            </div>
            <EvidenceBadge enough={answer.enough_evidence} status={answer.evidence_status} />
            <p className="excerpt">{citation.excerpt}</p>
          </button>
        );
      })}
    </div>
  );
}
