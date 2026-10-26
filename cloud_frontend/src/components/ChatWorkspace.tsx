"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CitationPanel } from "@/components/CitationPanel";
import { EmptyState } from "@/components/EmptyState";
import { EvidenceBadge, StatusBadge } from "@/components/StatusBadge";
import { PdfViewer } from "@/components/PdfViewer";
import { getClient } from "@/lib/api";
import { isWithheldAnswer, type Citation, type Document } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/AuthProvider";
import { useApiGuard } from "@/lib/auth/useApiGuard";
import { loadHistory, saveHistory, type ChatTurn } from "@/lib/chat/history";
import { DOCUMENT_POLL_MS, MAX_QUESTION_CHARS, MIN_QUESTION_CHARS } from "@/lib/config";
import { validateQuestion } from "@/lib/pdf/validate";

export function ChatWorkspace({ documentId }: { documentId: string }) {
  const { getAccessToken, session } = useAuth();
  const client = useMemo(() => getClient(getAccessToken), [getAccessToken]);
  const guard = useApiGuard();
  const userId = session?.user.id || "anon";
  const [doc, setDoc] = useState<Document | null>(null);
  const [turns, setTurns] = useState<ChatTurn[] | null>(null);
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeCite, setActiveCite] = useState<Citation | null>(null);

  const visibleTurns = turns ?? [];
  const lastOk = [...visibleTurns].reverse().find((t) => t.status === "ok" && t.answer);

  useEffect(() => {
    setTurns(loadHistory(userId, documentId));
  }, [documentId, userId]);

  useEffect(() => {
    if (turns === null) return;
    saveHistory(userId, documentId, turns);
  }, [documentId, turns, userId]);

  const loadDoc = useCallback(async () => {
    const next = await client.getDocument(documentId);
    setDoc(next);
    setError("");
  }, [client, documentId]);

  useEffect(() => {
    void loadDoc().catch(async (err) => setError(await guard(err)));
  }, [guard, loadDoc]);

  useEffect(() => {
    if (!doc || (doc.status !== "queued" && doc.status !== "processing")) return;
    const timer = window.setInterval(() => {
      void loadDoc().catch(async (err) => setError(await guard(err)));
    }, DOCUMENT_POLL_MS);
    return () => window.clearInterval(timer);
  }, [doc, guard, loadDoc]);

  async function ask() {
    const check = validateQuestion(question, MIN_QUESTION_CHARS, MAX_QUESTION_CHARS);
    if (!check.ok) {
      setError(check.message);
      return;
    }
    if (!doc || doc.status !== "ready") {
      setError("Wait until this PDF is ready before asking.");
      return;
    }
    const turn: ChatTurn = {
      id: crypto.randomUUID(),
      question: question.trim(),
      createdAt: new Date().toISOString(),
      status: "pending",
    };
    setTurns((prev) => [...(prev ?? []), turn]);
    setBusy(true);
    setError("");
    setStatus("Searching, reranking, and writing an answer…");
    try {
      const answer = await client.chat(documentId, question.trim());
      setTurns((prev) =>
        (prev ?? []).map((item) => (item.id === turn.id ? { ...item, status: "ok" as const, answer } : item)),
      );
      setActiveCite(answer.citations[0] || null);
      setQuestion("");
      setStatus("");
    } catch (err) {
      const message = await guard(err);
      setTurns((prev) =>
        (prev ?? []).map((item) =>
          item.id === turn.id ? { ...item, status: "error" as const, error: message } : item,
        ),
      );
      setError(message);
      setStatus("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <p>
        <Link href="/library">← Library</Link>
      </p>
      <section className="hero">
        <h1>{doc?.title || "Chat"}</h1>
        <p>
          {doc ? (
            <>
              {doc.filename} <StatusBadge status={doc.status} />
            </>
          ) : (
            "Loading document…"
          )}
        </p>
      </section>

      <div className="chat-desk">
        <div>
          <div className="ask-row">
            <textarea
              value={question}
              maxLength={MAX_QUESTION_CHARS}
              disabled={busy || doc?.status !== "ready"}
              placeholder={
                doc?.status === "ready"
                  ? "Ask a question about this PDF"
                  : "Indexing must finish before you can ask"
              }
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void ask();
              }}
              aria-label="Question"
            />
            <button type="button" onClick={() => void ask()} disabled={busy || doc?.status !== "ready"} aria-label="Ask">
              →
            </button>
          </div>
          <p className="status" aria-live="polite">
            {status}
            {question.trim().length > 0 && question.trim().length < MIN_QUESTION_CHARS
              ? ` ${MIN_QUESTION_CHARS - question.trim().length} more characters needed.`
              : ""}
          </p>
          {error ? (
            <p className="error-card" role="alert">
              {error}
            </p>
          ) : null}

          <div className="history">
            {visibleTurns.length === 0 ? (
              <EmptyState title="No questions yet">
                Ask something the PDF can actually answer. Try a refusal such as “What is Arjuna’s
                email address?” to see honest ungrounded handling.
              </EmptyState>
            ) : null}
            {visibleTurns.map((turn) => (
              <article key={turn.id}>
                <div className="bubble-q">{turn.question}</div>
                {turn.status === "pending" ? (
                  <div className="empty pulse">Finding passages and writing an answer…</div>
                ) : null}
                {turn.status === "error" ? <div className="error-card">{turn.error}</div> : null}
                {turn.answer ? (
                  <div className="answer-card">
                    <EvidenceBadge
                      enough={turn.answer.enough_evidence}
                      status={turn.answer.evidence_status}
                    />
                    <p className="answer-text">
                      {isWithheldAnswer(turn.answer)
                        ? "The model claimed support without a valid citation, so this answer is withheld."
                        : turn.answer.answer}
                    </p>
                    <div className="metrics">
                      <div className="metric">
                        <span className="k">Search</span>
                        <span>{turn.answer.timings_ms.search} ms</span>
                      </div>
                      <div className="metric">
                        <span className="k">Rerank</span>
                        <span>{turn.answer.timings_ms.rerank} ms</span>
                      </div>
                      <div className="metric">
                        <span className="k">Answer</span>
                        <span>{turn.answer.timings_ms.answer} ms</span>
                      </div>
                    </div>
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </div>

        <aside>
          <h2>Evidence</h2>
          <CitationPanel
            answer={lastOk?.answer || null}
            filename={doc?.filename || "document.pdf"}
            selected={activeCite}
            onSelect={setActiveCite}
          />
          {activeCite ? (
            <div style={{ marginTop: "1rem" }}>
              <PdfViewer
                documentId={documentId}
                filename={doc?.filename || "document.pdf"}
                page={activeCite.pdf_page}
                client={client}
              />
            </div>
          ) : (
            <p className="empty" style={{ marginTop: "1rem" }}>
              Click a citation to open that PDF page.
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}
