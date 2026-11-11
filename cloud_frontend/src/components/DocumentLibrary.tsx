"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { StatusBadge } from "@/components/StatusBadge";
import { UploadDropzone } from "@/components/UploadDropzone";
import { getClient } from "@/lib/api";
import type { Document, MeResponse } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/AuthProvider";
import { useApiGuard } from "@/lib/auth/useApiGuard";
import { DAILY_QUESTION_LIMIT, DAILY_UPLOAD_LIMIT, DOCUMENT_POLL_MS } from "@/lib/config";

export function DocumentLibrary() {
  const { getAccessToken, session } = useAuth();
  const client = useMemo(() => getClient(getAccessToken), [getAccessToken]);
  const guard = useApiGuard();
  const [docs, setDocs] = useState<Document[]>([]);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<Document | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "ready" | "processing">("all");

  const refresh = useCallback(async () => {
    const [nextDocs, nextMe] = await Promise.all([client.listDocuments(), client.me()]);
    setDocs(nextDocs);
    setMe(nextMe);
    setSelected((current) => nextDocs.some((doc) => doc.id === current) ? current : nextDocs[0]?.id || null);
    window.dispatchEvent(new CustomEvent("bookrag-documents-loaded", {
      detail: { userId: session?.user.id, documentIds: nextDocs.map((doc) => doc.id) },
    }));
  }, [client, session?.user.id]);

  useEffect(() => {
    let cancelled = false;
    void refresh()
      .catch(async (err) => {
        if (!cancelled) setError(await guard(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [guard, refresh]);

  useEffect(() => {
    const busy = docs.some((d) => d.status === "queued" || d.status === "processing");
    if (!busy) return;
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, DOCUMENT_POLL_MS);
    return () => window.clearInterval(timer);
  }, [docs, refresh]);

  const visibleDocs = docs.filter((doc) => {
    const matchesSearch = `${doc.title} ${doc.filename}`.toLowerCase().includes(search.trim().toLowerCase());
    const matchesFilter = filter === "all" || (filter === "ready" ? doc.status === "ready" : doc.status === "queued" || doc.status === "processing");
    return matchesSearch && matchesFilter;
  });
  const selectedDoc = visibleDocs.find((d) => d.id === selected) || null;

  async function onUpload(file: File) {
    setError("");
    try {
      const created = await client.uploadDocument(file);
      await refresh();
      setSearch("");
      setFilter("all");
      setSelected(created.id);
    } catch (err) {
      throw new Error(await guard(err));
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await client.deleteDocument(pendingDelete.id);
      setPendingDelete(null);
      await refresh();
    } catch (err) {
      setError(await guard(err));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="page library-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR PRIVATE COLLECTION</p>
          <h1>Personal Library</h1>
          <p>Upload a PDF, then ask questions with passages and page citations from that book.</p>
        </div>
        <div className="usage" aria-label="Daily usage">
          <span>Uploads {me?.daily_uploads_used ?? "—"}/{DAILY_UPLOAD_LIMIT}</span>
          <span>Questions {me?.daily_questions_used ?? "—"}/{DAILY_QUESTION_LIMIT}</span>
          {client.mode === "mock" ? <span>Mock preview</span> : null}
        </div>
      </div>

      {error ? <p className="error-card" role="alert">{error}</p> : null}

      {docs.length > 0 ? <div className="library-toolbar">
        <label className="library-search">
          <span className="sr-only">Search your library</span>
          <span aria-hidden="true">⌕</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search your library…" />
        </label>
        <div className="library-filters" role="group" aria-label="Filter PDFs">
          <button type="button" className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>All books ({docs.length})</button>
          <button type="button" className={filter === "ready" ? "active" : ""} onClick={() => setFilter("ready")}>Ready</button>
          <button type="button" className={filter === "processing" ? "active" : ""} onClick={() => setFilter("processing")}>Processing</button>
        </div>
      </div> : null}

      {loading ? <p className="status pulse">Loading documents…</p> : null}
      {!loading && docs.length === 0 ? (
        <div className="library-welcome" id="books">
          <div>
            <p className="eyebrow">START HERE</p>
            <h2>Your library starts with a PDF</h2>
            <p>Upload a digital-text PDF. BookRAG will prepare it for search, then you can ask questions and check answers against the original pages.</p>
          </div>
          <div className="welcome-upload"><UploadDropzone onFile={onUpload} /></div>
        </div>
      ) : null}

      {!loading && docs.length > 0 ? <div className="book-grid" role="list" id="books">
        {visibleDocs.map((doc, index) => (
          <article className={`book-card ${selected === doc.id ? "selected" : ""}`} key={doc.id} role="listitem">
            <button type="button" className="book-select" aria-pressed={selected === doc.id} onClick={() => setSelected(doc.id)}>
              <span className={`book-cover cover-${index % 4}`} aria-hidden="true">
                <span className="book-cover-mark">BookRAG</span>
                <span className="book-cover-title">{doc.title}</span>
                <span className="book-cover-bottom">PDF</span>
              </span>
              <span className="book-name">{doc.title}</span>
              <span className="book-file">{doc.filename}</span>
            </button>
            <div className="book-card-footer">
              <StatusBadge status={doc.status} />
              {doc.page_count > 0 ? <span>{doc.page_count} PDF pages</span> : null}
            </div>
            {doc.status === "ready" ? <Link className="book-ask" href={`/chat/${doc.id}`}>Ask about this PDF <span aria-hidden="true">→</span></Link> : null}
            <div className="book-remove-row">
              <button type="button" className="book-delete" aria-label={`Remove ${doc.title}`} onClick={() => setPendingDelete(doc)}>Remove PDF</button>
            </div>
          </article>
        ))}
        <div className="book-upload" role="listitem">
          <span className="upload-icon" aria-hidden="true">＋</span>
          <h2>Upload another PDF</h2>
          <UploadDropzone onFile={onUpload} />
        </div>
      </div> : null}
      {!loading && docs.length > 0 && visibleDocs.length === 0 ? <p className="empty">No PDFs match this search or filter.</p> : null}

      {selectedDoc ? (
        <section className="document-detail" aria-label="Selected PDF details">
          <div>
            <p className="eyebrow">SELECTED PDF</p>
            <h2>{selectedDoc.title}</h2>
            <p className="document-detail-meta">{selectedDoc.filename}{selectedDoc.page_count > 0 ? ` · ${selectedDoc.page_count} PDF pages` : ""}{selectedDoc.passage_count > 0 ? ` · ${selectedDoc.passage_count} passages` : ""}</p>
            {selectedDoc.error ? <p className="error-card">{selectedDoc.error}</p> : null}
            {selectedDoc.status === "ready" ? <p>Your PDF is ready. Open it to ask a question and check the cited page.</p> : null}
            {selectedDoc.status === "queued" || selectedDoc.status === "processing" ? (
              <div className="processing-summary" aria-label="PDF processing progress">
                <p>We are preparing this PDF. You can leave this page and return later; the status updates automatically.</p>
                <ol>
                  <li className="done"><span>1</span> PDF received</li>
                  <li className="current"><span>2</span> Preparing text and search index</li>
                  <li><span>3</span> Ready for questions</li>
                </ol>
                <small>Detailed stage times are not available from the server yet.</small>
              </div>
            ) : null}
            {selectedDoc.status === "failed" ? <p>We could not prepare this PDF. Remove it and try a digital-text PDF.</p> : null}
          </div>
          <div className="document-detail-action">
            <StatusBadge status={selectedDoc.status} />
            {selectedDoc.status === "ready" ? <Link className="primary" href={`/chat/${selectedDoc.id}`}>Ask a question <span aria-hidden="true">→</span></Link> : null}
          </div>
        </section>
      ) : null}

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
