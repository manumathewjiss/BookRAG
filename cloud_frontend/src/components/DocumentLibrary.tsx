"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { StatusBadge } from "@/components/StatusBadge";
import { UploadDropzone } from "@/components/UploadDropzone";
import { errorMessage, getClient } from "@/lib/api";
import type { Document, MeResponse } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/AuthProvider";
import { DAILY_QUESTION_LIMIT, DAILY_UPLOAD_LIMIT, DOCUMENT_POLL_MS } from "@/lib/config";

export function DocumentLibrary() {
  const { getAccessToken, session } = useAuth();
  const client = useMemo(() => getClient(getAccessToken), [getAccessToken]);
  const [docs, setDocs] = useState<Document[]>([]);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<Document | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const [nextDocs, nextMe] = await Promise.all([client.listDocuments(), client.me()]);
    setDocs(nextDocs);
    setMe(nextMe);
    setSelected((current) => current || nextDocs[0]?.id || null);
  }, [client]);

  useEffect(() => {
    let cancelled = false;
    void refresh()
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  useEffect(() => {
    const busy = docs.some((d) => d.status === "queued" || d.status === "processing");
    if (!busy) return;
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, DOCUMENT_POLL_MS);
    return () => window.clearInterval(timer);
  }, [docs, refresh]);

  const selectedDoc = docs.find((d) => d.id === selected) || null;

  async function onUpload(file: File) {
    setError("");
    const created = await client.uploadDocument(file);
    await refresh();
    setSelected(created.id);
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await client.deleteDocument(pendingDelete.id);
      setPendingDelete(null);
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="page">
      <section className="hero">
        <h1>Your library</h1>
        <p>
          Private PDFs for {session?.user.email}. Select a ready document to chat. Indexing status
          updates automatically.
        </p>
        <div className="usage">
          <span>
            Uploads today: {me?.daily_uploads_used ?? "—"} / {DAILY_UPLOAD_LIMIT}
          </span>
          <span>
            Questions today: {me?.daily_questions_used ?? "—"} / {DAILY_QUESTION_LIMIT}
          </span>
          <span>API: {client.mode === "mock" ? "mock (not live)" : "live FastAPI"}</span>
        </div>
      </section>

      <div className="library-grid">
        <div>
          <UploadDropzone onFile={onUpload} />
          {error ? (
            <p className="error-card" role="alert">
              {error}
            </p>
          ) : null}
        </div>
        <div>
          {loading ? (
            <p className="status pulse">Loading documents…</p>
          ) : docs.length === 0 ? (
            <EmptyState title="No PDFs yet">
              Drop a PDF on the left. When status is Ready, open chat and ask a question grounded in
              that file.
            </EmptyState>
          ) : (
            <div className="doc-list" role="list">
              {docs.map((doc) => (
                <div className="doc-row" key={doc.id} role="listitem">
                  <button
                    type="button"
                    className={`doc-card ${selected === doc.id ? "active" : ""}`}
                    aria-pressed={selected === doc.id}
                    onClick={() => setSelected(doc.id)}
                  >
                    <span className="spine" aria-hidden="true">
                      {doc.title.slice(0, 3).toUpperCase()}
                    </span>
                    <span>
                      <span className="doc-name">{doc.title}</span>
                      <span className="doc-tag">
                        {doc.filename} · {doc.page_count} pages · {doc.passage_count} passages
                      </span>
                    </span>
                    <StatusBadge status={doc.status} />
                  </button>
                  <button
                    type="button"
                    className="danger"
                    aria-label={`Delete ${doc.title}`}
                    onClick={() => setPendingDelete(doc)}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          {selectedDoc ? (
            <div className="card" style={{ marginTop: "1rem" }}>
              <h2 style={{ marginTop: 0 }}>{selectedDoc.title}</h2>
              {selectedDoc.error ? <p className="error-card">{selectedDoc.error}</p> : null}
              {selectedDoc.status === "ready" ? (
                <Link className="primary" href={`/chat/${selectedDoc.id}`} style={{ display: "inline-block" }}>
                  Open chat
                </Link>
              ) : selectedDoc.status === "failed" ? (
                <p>This PDF failed to index. Remove it and try a digital-text PDF.</p>
              ) : (
                <p className="status pulse">Indexing… chat unlocks when this document is ready.</p>
              )}
            </div>
          ) : null}
        </div>
      </div>

      {pendingDelete ? (
        <ConfirmDialog
          title="Remove this PDF?"
          body={`Delete ${pendingDelete.filename} from your private library. This cannot be undone in the UI.`}
          confirmLabel="Delete"
          busy={deleting}
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => void confirmDelete()}
        />
      ) : null}
    </div>
  );
}
