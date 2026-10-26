import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CitationPanel } from "@/components/CitationPanel";
import { EmptyState } from "@/components/EmptyState";
import { EvidenceBadge, StatusBadge } from "@/components/StatusBadge";
import type { Answer } from "@/lib/api/types";

const grounded: Answer = {
  answer: "A high-level language is easy for humans to read.",
  enough_evidence: true,
  evidence_status: "direct_answer",
  citations: [
    {
      passage_id: "p1",
      pdf_page: 23,
      excerpt: "A high-level language is a programming language like Python.",
    },
  ],
  timings_ms: { search: 1, rerank: 1, answer: 1 },
  usage: { input_tokens: 1, output_tokens: 1, estimated_usd: 0 },
};

const refusal: Answer = {
  answer: "The uploaded PDF does not confirm that.",
  enough_evidence: false,
  evidence_status: "absent",
  citations: [],
  timings_ms: { search: 1, rerank: 1, answer: 1 },
  usage: { input_tokens: 1, output_tokens: 1, estimated_usd: 0 },
};

describe("UI pieces", () => {
  it("shows empty-library copy", () => {
    render(<EmptyState title="No PDFs yet">Drop a PDF to get started.</EmptyState>);
    expect(screen.getByText("No PDFs yet")).toBeInTheDocument();
  });

  it("labels document status", () => {
    render(<StatusBadge status="processing" />);
    expect(screen.getByText("Indexing")).toBeInTheDocument();
  });

  it("renders clickable citations with filename, page, and excerpt", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <CitationPanel
        answer={grounded}
        filename="thinkpython.pdf"
        selected={null}
        onSelect={onSelect}
      />,
    );
    expect(screen.getByText(/thinkpython\.pdf · p\. 23/)).toBeInTheDocument();
    expect(screen.getByText(/high-level language/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /thinkpython\.pdf/i }));
    expect(onSelect).toHaveBeenCalledWith(grounded.citations[0]);
  });

  it("labels unverified Sol answers as withheld", () => {
    render(<EvidenceBadge enough={false} status="unverified" />);
    expect(screen.getByText(/Answer withheld/)).toBeInTheDocument();
  });

  it("does not offer citations when evidence is unverified", () => {
    const unverified: Answer = {
      ...grounded,
      enough_evidence: true,
      evidence_status: "unverified",
      citations: [],
      answer: "This claimed answer must not be treated as cited support.",
    };
    render(
      <CitationPanel answer={unverified} filename="thinkpython.pdf" selected={null} onSelect={() => undefined} />,
    );
    expect(screen.getByText(/Answer withheld/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /thinkpython\.pdf/i })).not.toBeInTheDocument();
  });

  it("shows refusal copy when evidence is absent", () => {
    render(
      <CitationPanel answer={refusal} filename="thinkpython.pdf" selected={null} onSelect={() => undefined} />,
    );
    expect(screen.getByText("Not in this PDF")).toBeInTheDocument();
    expect(screen.getByText(/No cited passage was returned/)).toBeInTheDocument();
  });
});
