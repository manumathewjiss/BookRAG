/** Types aligned with Codex `cloud_backend/API_CONTRACT_v1.md` and `schemas.py`. */

import type { AnswerLanguage } from "@/lib/chat/answer-language";

export type DocumentStatus = "queued" | "processing" | "ready" | "failed";

export type EvidenceStatus = "direct_answer" | "nearby_only" | "absent" | "unverified";

export interface Document {
  id: string;
  is_sample?: boolean;
  title: string;
  filename: string;
  status: DocumentStatus;
  page_count: number;
  passage_count: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  passage_id: string;
  pdf_page: number;
  excerpt: string;
}

export interface Timings {
  search: number;
  rerank: number;
  answer: number;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  estimated_usd: number;
}

export interface Answer {
  answer: string;
  enough_evidence: boolean;
  evidence_status: EvidenceStatus;
  citations: Citation[];
  timings_ms: Timings;
  usage: Usage;
  reused_answer?: boolean;
  answer_language?: AnswerLanguage;
}

export interface MeResponse {
  user_id: string;
  daily_questions_used: number;
  daily_uploads_used: number;
}

export interface HealthResponse {
  status: "ok";
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
  };
}

export interface ChatRequest {
  question: string;
  answer_language?: AnswerLanguage;
  question_language?: AnswerLanguage;
  preview_token?: string;
}

export interface QuestionPreview {
  original_question: string;
  question_language: AnswerLanguage;
  native_script: string;
  english_meaning: string;
  needs_clarification: boolean;
  preview_token: string | null;
}

export const DOCUMENT_STATUSES: readonly DocumentStatus[] = [
  "queued",
  "processing",
  "ready",
  "failed",
];

export const EVIDENCE_STATUSES: readonly EvidenceStatus[] = [
  "direct_answer",
  "nearby_only",
  "absent",
  "unverified",
];

export function isDocumentStatus(value: string): value is DocumentStatus {
  return (DOCUMENT_STATUSES as readonly string[]).includes(value);
}

export function isEvidenceStatus(value: string): value is EvidenceStatus {
  return (EVIDENCE_STATUSES as readonly string[]).includes(value);
}

export function isWithheldAnswer(answer: Pick<Answer, "evidence_status">): boolean {
  return answer.evidence_status === "unverified";
}

export interface BookragClient {
  readonly mode: "mock" | "live";
  health(): Promise<HealthResponse>;
  me(): Promise<MeResponse>;
  listDocuments(): Promise<Document[]>;
  getDocument(id: string): Promise<Document>;
  getPdf(id: string): Promise<ArrayBuffer>;
  uploadDocument(file: File, title?: string): Promise<Document>;
  deleteDocument(id: string): Promise<void>;
  prepareQuestion(documentId: string, question: string, language: AnswerLanguage): Promise<QuestionPreview>;
  transcribeQuestion(documentId: string, audio: File, language: AnswerLanguage): Promise<string>;
  chat(documentId: string, question: string, language?: AnswerLanguage,
       questionLanguage?: AnswerLanguage, previewToken?: string | null): Promise<Answer>;
}
