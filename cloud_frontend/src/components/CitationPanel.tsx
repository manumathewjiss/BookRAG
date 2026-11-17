"use client";

import type { Answer, Citation } from "@/lib/api/types";
import { EvidenceBadge } from "@/components/StatusBadge";
import { evidencePreview } from "@/lib/chat/display";

export function CitationPanel({
  answer,
  question,
  filename,
  sampleMode = false,
  selected,
  onSelect,
}: {
  answer: Answer | null;
  question: string;
  filename: string;
  sampleMode?: boolean;
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
  if (answer.evidence_status === "unverified" || !answer.enough_evidence || answer.citations.length === 0) {
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
        const preview = sampleMode ? citation.excerpt : evidencePreview(citation.excerpt, question, answer.answer);
        return (
          <article key={citation.passage_id} className={`cite-card ${active ? "active" : ""}`}>
            {sampleMode ? <div className="cite-select">
              <span className="cite-heading"><strong>{filename} · p. {citation.pdf_page}</strong><span>{index + 1}/{answer.citations.length}</span></span>
              <EvidenceBadge enough={answer.enough_evidence} status={answer.evidence_status} />
              {preview ? <span className="excerpt">{preview}</span> : null}
            </div> : <button type="button" className="cite-select" aria-pressed={active} onClick={() => onSelect(citation)}>
              <span className="cite-heading"><strong>{filename} · p. {citation.pdf_page}</strong><span>{index + 1}/{answer.citations.length}</span></span>
              <EvidenceBadge enough={answer.enough_evidence} status={answer.evidence_status} />
              {preview ? <span className="excerpt">{preview}</span> : <span className="excerpt-note">No reliable short excerpt found. Open the full passage to check this citation.</span>}
            </button>}
            {!sampleMode ? <details className="full-passage"><summary>Show full passage</summary><p>{citation.excerpt}</p></details> : null}
          </article>
        );
      })}
    </div>
  );
}
