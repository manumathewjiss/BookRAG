import { apiBaseUrl, isMockMode, MAX_QUESTION_CHARS, MIN_QUESTION_CHARS } from "@/lib/config";
import { BookragApiError, parseApiError } from "@/lib/api/errors";
import { createMockClient } from "@/lib/api/mock";
import { isMockAccessToken } from "@/lib/auth/token";
import type { Answer, BookragClient, Document, HealthResponse, MeResponse } from "@/lib/api/types";
import { isDocumentStatus, isEvidenceStatus } from "@/lib/api/types";

export type { BookragClient } from "@/lib/api/types";

export type AccessTokenProvider = () => Promise<string | null>;

async function requireLiveToken(getToken: AccessTokenProvider): Promise<string> {
  const token = await getToken();
  if (!token || isMockAccessToken(token)) {
    throw new BookragApiError("Sign in to continue.", "unauthenticated", 401);
  }
  return token;
}

function assertDocument(value: unknown): Document {
  const rec = value && typeof value === "object" ? (value as Record<string, unknown>) : null;
  if (!rec || typeof rec.id !== "string" || typeof rec.filename !== "string") {
    throw new BookragApiError("Unexpected document payload.", "invalid_response", 500);
  }
  const status = String(rec.status || "");
  if (!isDocumentStatus(status)) {
    throw new BookragApiError("Unexpected document status.", "invalid_response", 500);
  }
  return {
    id: rec.id,
    is_sample: rec.is_sample === true,
    title: String(rec.title || rec.filename),
    filename: rec.filename,
    status,
    page_count: Number(rec.page_count || 0),
    passage_count: Number(rec.passage_count || 0),
    error: rec.error == null ? null : String(rec.error),
    created_at: String(rec.created_at || ""),
    updated_at: String(rec.updated_at || ""),
  };
}

function assertAnswer(value: unknown): Answer {
  const rec = value && typeof value === "object" ? (value as Record<string, unknown>) : null;
  if (!rec || typeof rec.answer !== "string") {
    throw new BookragApiError("Unexpected answer payload.", "invalid_response", 500);
  }
  const evidence = String(rec.evidence_status || "");
  if (!isEvidenceStatus(evidence)) {
    throw new BookragApiError("Unexpected evidence status.", "invalid_response", 500);
  }
  const citations = Array.isArray(rec.citations) ? rec.citations : [];
  const timings = (rec.timings_ms && typeof rec.timings_ms === "object"
    ? rec.timings_ms
    : {}) as Record<string, unknown>;
  const usage = (rec.usage && typeof rec.usage === "object" ? rec.usage : {}) as Record<
    string,
    unknown
  >;
  return {
    answer: rec.answer,
    enough_evidence: Boolean(rec.enough_evidence),
    evidence_status: evidence,
    citations: citations.map((item) => {
      const c = item as Record<string, unknown>;
      return {
        passage_id: String(c.passage_id || ""),
        pdf_page: Number(c.pdf_page || 0),
        excerpt: String(c.excerpt || ""),
      };
    }),
    timings_ms: {
      search: Number(timings.search || 0),
      rerank: Number(timings.rerank || 0),
      answer: Number(timings.answer || 0),
    },
    usage: {
      input_tokens: Number(usage.input_tokens || 0),
      output_tokens: Number(usage.output_tokens || 0),
      estimated_usd: Number(usage.estimated_usd || 0),
    },
    reused_answer: Boolean(rec.reused_answer),
  };
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return { error: { code: "invalid_json", message: "The server returned an unreadable response." } };
  }
}

export function createLiveClient(getToken: AccessTokenProvider): BookragClient {
  const base = apiBaseUrl();

  async function request(path: string, init: RequestInit = {}): Promise<{ status: number; body: unknown }> {
    const token = await requireLiveToken(getToken);
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    let response: Response;
    try {
      response = await fetch(`${base}${path}`, { ...init, headers });
    } catch {
      throw new BookragApiError(
        "Could not reach the BookRAG API. Check that the backend is running.",
        "network",
        503,
      );
    }
    const body = await readJson(response);
    return { status: response.status, body };
  }

  return {
    mode: "live",
    async health() {
      const response = await fetch(`${base}/api/v1/health`);
      const body = await readJson(response);
      if (!response.ok) throw parseApiError(response.status, body);
      return body as HealthResponse;
    },
    async me() {
      const { status, body } = await request("/api/v1/me");
      if (status !== 200) throw parseApiError(status, body);
      const rec = body as MeResponse;
      return {
        user_id: String(rec.user_id),
        daily_questions_used: Number(rec.daily_questions_used || 0),
        daily_uploads_used: Number(rec.daily_uploads_used || 0),
      };
    },
    async listDocuments() {
      const { status, body } = await request("/api/v1/documents");
      if (status !== 200) throw parseApiError(status, body);
      const docs = (body as { documents?: unknown[] }).documents || [];
      return docs.map(assertDocument);
    },
    async getDocument(id: string) {
      const { status, body } = await request(`/api/v1/documents/${encodeURIComponent(id)}`);
      if (status !== 200) throw parseApiError(status, body);
      return assertDocument((body as { document: unknown }).document);
    },
    async getPdf(id: string) {
      const token = await requireLiveToken(getToken);
      let response: Response;
      try {
        response = await fetch(`${base}/api/v1/documents/${encodeURIComponent(id)}/pdf`, {
          headers: { Authorization: `Bearer ${token}` },
          cache: "no-store",
        });
      } catch {
        throw new BookragApiError("Could not reach the BookRAG API.", "network", 503);
      }
      if (!response.ok) throw parseApiError(response.status, await readJson(response));
      if (!(response.headers.get("content-type") || "").includes("application/pdf")) {
        throw new BookragApiError("The server did not return a PDF.", "invalid_response", 503);
      }
      return response.arrayBuffer();
    },
    async getCitationPagePdf(id: string, passageId: string) {
      const token = await requireLiveToken(getToken);
      let response: Response;
      try {
        response = await fetch(`${base}/api/v1/documents/${encodeURIComponent(id)}/citations/${encodeURIComponent(passageId)}/page`, {
          headers: { Authorization: `Bearer ${token}` },
          cache: "no-store",
        });
      } catch {
        throw new BookragApiError("Could not reach the BookRAG API.", "network", 503);
      }
      if (!response.ok) throw parseApiError(response.status, await readJson(response));
      if (!(response.headers.get("content-type") || "").includes("application/pdf")) {
        throw new BookragApiError("The server did not return a PDF page.", "invalid_response", 503);
      }
      return response.arrayBuffer();
    },
    async uploadDocument(file: File, title?: string) {
      const form = new FormData();
      form.append("file", file, file.name);
      if (title) form.append("title", title);
      const { status, body } = await request("/api/v1/documents", { method: "POST", body: form });
      if (status !== 202 && status !== 200) throw parseApiError(status, body);
      return assertDocument((body as { document: unknown }).document);
    },
    async deleteDocument(id: string) {
      const { status, body } = await request(`/api/v1/documents/${encodeURIComponent(id)}`, {
        method: "DELETE",
      });
      // Contract: 204 on deletion. 404 means the document is already gone from this account.
      if (status === 204 || status === 404) return;
      throw parseApiError(status, body);
    },
    async chat(documentId: string, question: string) {
      const trimmed = question.trim();
      if (trimmed.length < MIN_QUESTION_CHARS || trimmed.length > MAX_QUESTION_CHARS) {
        throw new BookragApiError(
          `Questions must be ${MIN_QUESTION_CHARS}–${MAX_QUESTION_CHARS} characters.`,
          "invalid_input",
          400,
        );
      }
      const { status, body } = await request(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chat`,
        { method: "POST", body: JSON.stringify({ question: trimmed }) },
      );
      if (status !== 200) throw parseApiError(status, body);
      return assertAnswer(body);
    },
  };
}

export function getClient(getToken: AccessTokenProvider): BookragClient {
  if (isMockMode()) return createMockClient();
  return createLiveClient(getToken);
}
