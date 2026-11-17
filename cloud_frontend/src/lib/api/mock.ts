import { BookragApiError } from "@/lib/api/errors";
import type { Answer, BookragClient, Document, MeResponse } from "@/lib/api/types";
import { MAX_PDF_BYTES, MAX_QUESTION_CHARS, MIN_QUESTION_CHARS } from "@/lib/config";
import type { AnswerLanguage } from "@/lib/chat/answer-language";

const READY_ID = "11111111-1111-4111-8111-111111111111";
const PROCESSING_ID = "22222222-2222-4222-8222-222222222222";

function nowIso(): string {
  return new Date().toISOString();
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function makeReadyDoc(): Document {
  const t = nowIso();
  return {
    id: READY_ID,
    title: "Think Python (mock)",
    filename: "thinkpython.pdf",
    status: "ready",
    page_count: 244,
    passage_count: 512,
    error: null,
    created_at: t,
    updated_at: t,
  };
}

function makeProcessingDoc(): Document {
  const t = nowIso();
  return {
    id: PROCESSING_ID,
    title: "NIST AI RMF (mock, still indexing)",
    filename: "nist-ai-rmf-1.0.pdf",
    status: "processing",
    page_count: 48,
    passage_count: 0,
    error: null,
    created_at: t,
    updated_at: t,
  };
}

const refusalTriggers = [/email address/i, /\bgdp\b/i, /tensorflow/i, /pytorch install/i];

function isRefusal(question: string): boolean {
  return refusalTriggers.some((re) => re.test(question));
}

function refusalAnswer(reused = false): Answer {
  return {
    answer:
      "The uploaded PDF does not confirm that. I can only answer from the selected document, and these pages do not contain that fact.",
    enough_evidence: false,
    evidence_status: "absent",
    citations: [],
    timings_ms: reused ? { search: 1, rerank: 0, answer: 0 } : { search: 42, rerank: 18, answer: 90 },
    usage: reused
      ? { input_tokens: 0, output_tokens: 0, estimated_usd: 0 }
      : { input_tokens: 800, output_tokens: 60, estimated_usd: 0.002 },
    reused_answer: reused,
  };
}

function unverifiedAnswer(reused = false): Answer {
  return {
    answer: "This text would have been shown if a citation had been returned.",
    enough_evidence: true,
    evidence_status: "unverified",
    citations: [],
    timings_ms: reused ? { search: 1, rerank: 0, answer: 0 } : { search: 20, rerank: 10, answer: 40 },
    usage: reused
      ? { input_tokens: 0, output_tokens: 0, estimated_usd: 0 }
      : { input_tokens: 400, output_tokens: 40, estimated_usd: 0.001 },
    reused_answer: reused,
  };
}

function supportedAnswer(reused = false): Answer {
  return {
    answer:
      "A high-level language is one that is designed to be easy for humans to read and write. Think Python also notes that Python is portable: the same program can run on different operating systems.",
    enough_evidence: true,
    evidence_status: "direct_answer",
    citations: [
      {
        passage_id: "aaaaaaa1-1111-4111-8111-111111111111",
        pdf_page: 23,
        excerpt:
          "A high-level language is a programming language like Python that is designed to be easy for humans to read and write.",
      },
      {
        passage_id: "aaaaaaa2-1111-4111-8111-111111111111",
        pdf_page: 23,
        excerpt: "Portable means that the program can run on different kinds of computers with few or no changes.",
      },
    ],
    timings_ms: reused ? { search: 1, rerank: 0, answer: 0 } : { search: 110, rerank: 240, answer: 820 },
    usage: reused
      ? { input_tokens: 0, output_tokens: 0, estimated_usd: 0 }
      : { input_tokens: 1400, output_tokens: 180, estimated_usd: 0.012 },
    reused_answer: reused,
  };
}

let mockSingleton: BookragClient | null = null;

export function createMockClient(): BookragClient {
  if (!mockSingleton) mockSingleton = buildMockClient();
  return mockSingleton;
}

/** Test helper: drop the in-memory library so cases stay isolated. */
export function resetMockClient(): void {
  mockSingleton = null;
}

function buildMockClient(): BookragClient {
  const docs = new Map<string, Document>([
    [READY_ID, makeReadyDoc()],
    [PROCESSING_ID, makeProcessingDoc()],
  ]);
  let questionsUsed = 3;
  let uploadsUsed = 1;
  const processingStarted = Date.now();
  /** Mock only: per-document exact question text → prior answer. Not browser localStorage. */
  const savedAnswers = new Map<string, Answer>();

  function maybeAdvance(): void {
    const processing = docs.get(PROCESSING_ID);
    if (processing && processing.status === "processing" && Date.now() - processingStarted > 2500) {
      docs.set(PROCESSING_ID, {
        ...processing,
        status: "ready",
        passage_count: 81,
        updated_at: nowIso(),
      });
    }
  }

  return {
    mode: "mock",
    async health() {
      return { status: "ok" };
    },
    async me(): Promise<MeResponse> {
      maybeAdvance();
      return {
        user_id: "00000000-0000-4000-8000-000000000001",
        daily_questions_used: questionsUsed,
        daily_uploads_used: uploadsUsed,
      };
    },
    async listDocuments() {
      maybeAdvance();
      return [...docs.values()].map(clone);
    },
    async getDocument(id: string) {
      maybeAdvance();
      const doc = docs.get(id);
      if (!doc) throw new BookragApiError("Document not found.", "not_found", 404);
      return clone(doc);
    },
    async getPdf(id: string) {
      maybeAdvance();
      const doc = docs.get(id);
      if (!doc) throw new BookragApiError("Document not found.", "not_found", 404);
      return mockPdfBytes().buffer.slice(0) as ArrayBuffer;
    },
    async uploadDocument(file: File, title?: string) {
      if (file.size > MAX_PDF_BYTES) {
        throw new BookragApiError("That PDF is too large.", "payload_too_large", 413);
      }
      const name = file.name || "upload.pdf";
      if (!name.toLowerCase().endsWith(".pdf")) {
        throw new BookragApiError("Please attach a PDF file.", "invalid_input", 400);
      }
      const id = crypto.randomUUID();
      const t = nowIso();
      const doc: Document = {
        id,
        title: title || name.replace(/\.pdf$/i, ""),
        filename: name,
        status: "queued",
        page_count: 0,
        passage_count: 0,
        error: null,
        created_at: t,
        updated_at: t,
      };
      docs.set(id, doc);
      uploadsUsed += 1;
      window.setTimeout(() => {
        const current = docs.get(id);
        if (!current) return;
        docs.set(id, { ...current, status: "processing", updated_at: nowIso() });
      }, 400);
      window.setTimeout(() => {
        const current = docs.get(id);
        if (!current) return;
        docs.set(id, {
          ...current,
          status: "ready",
          page_count: Math.max(1, Math.round(file.size / 45000)),
          passage_count: 24,
          updated_at: nowIso(),
        });
      }, 1800);
      return clone(doc);
    },
    async deleteDocument(id: string) {
      if (id === READY_ID || id === PROCESSING_ID) {
        // Seed docs can be removed in the mock library like user uploads.
      }
      docs.delete(id);
    },
    async prepareQuestion(_documentId: string, question: string, language: AnswerLanguage) {
      return { original_question: question.trim(), question_language: language,
        native_script: question.trim(), english_meaning: question.trim(),
        needs_clarification: false, preview_token: "mock-preview" };
    },
    async chat(documentId: string, question: string, language: AnswerLanguage = "en") {
      maybeAdvance();
      const trimmed = question.trim();
      if (trimmed.length < MIN_QUESTION_CHARS || trimmed.length > MAX_QUESTION_CHARS) {
        throw new BookragApiError(
          `Questions must be ${MIN_QUESTION_CHARS}–${MAX_QUESTION_CHARS} characters.`,
          "invalid_input",
          400,
        );
      }
      const doc = docs.get(documentId);
      if (!doc) throw new BookragApiError("Document not found.", "not_found", 404);
      if (doc.status === "queued" || doc.status === "processing") {
        throw new BookragApiError("This PDF is still being indexed.", "still_processing", 409);
      }
      if (doc.status === "failed") {
        throw new BookragApiError(doc.error || "This PDF failed to index.", "invalid_input", 400);
      }
      questionsUsed += 1;
      const cacheKey = `${documentId}::${language}::${trimmed.toLowerCase()}`;
      const prior = savedAnswers.get(cacheKey);
      if (prior) {
        await new Promise((resolve) => window.setTimeout(resolve, 40));
        return clone({
          ...prior,
          reused_answer: true,
          timings_ms: { search: 1, rerank: 0, answer: 0 },
          usage: { input_tokens: 0, output_tokens: 0, estimated_usd: 0 },
        });
      }
      await new Promise((resolve) => window.setTimeout(resolve, 350));
      const next = /unverified/i.test(trimmed)
        ? unverifiedAnswer()
        : isRefusal(trimmed)
          ? refusalAnswer()
          : supportedAnswer();
      next.answer_language = language;
      if (language !== "en" && next.evidence_status !== "unverified") {
        next.answer = next.enough_evidence
          ? {
              hi: "उच्च स्तरीय भाषा मनुष्यों के लिए पढ़ना और लिखना आसान बनाती है। थिंक पाइथन यह भी बताती है कि पाइथन अलग-अलग कंप्यूटरों पर चल सकती है।",
              sa: "उच्चस्तरीया भाषा मनुष्याणां पठनलेखनाय सुलभा भवति। थिंक पाइथन इति पुस्तके पाइथन विविधेषु सङ्गणकेषु चलति इति अपि कथ्यते।",
              es: "Un lenguaje de alto nivel está diseñado para que las personas puedan leerlo y escribirlo con facilidad. Think Python también explica que Python puede ejecutarse en distintos tipos de computadoras.",
              ta: "உயர்நிலை மொழி மனிதர்கள் எளிதாகப் படிக்கவும் எழுதவும் உதவுகிறது. பல வகை கணினிகளில் பைதான் இயங்கும் என்றும் Think Python விளக்குகிறது.",
              te: "ఉన్నత స్థాయి భాషను మనుషులు సులభంగా చదవగలరు, రాయగలరు. పైథాన్ వివిధ రకాల కంప్యూటర్లలో పనిచేస్తుందని Think Python కూడా వివరిస్తుంది.",
              ml: "ഉയർന്ന തലത്തിലുള്ള ഭാഷ മനുഷ്യർക്ക് എളുപ്പത്തിൽ വായിക്കാനും എഴുതാനും സഹായിക്കുന്നു. പൈത്തൺ വിവിധ തരത്തിലുള്ള കമ്പ്യൂട്ടറുകളിൽ പ്രവർത്തിക്കുമെന്ന് Think Python വിശദീകരിക്കുന്നു.",
              bn: "উচ্চস্তরের ভাষা মানুষের পড়া ও লেখা সহজ করে। Think Python আরও ব্যাখ্যা করে যে পাইথন বিভিন্ন ধরনের কম্পিউটারে চলতে পারে।",
              fr: "Un langage de haut niveau est plus facile à lire et à écrire pour les humains. Think Python explique aussi que Python fonctionne sur différents ordinateurs.",
              it: "Un linguaggio di alto livello è più facile da leggere e scrivere per le persone. Think Python spiega anche che Python funziona su diversi computer.",
              gu: "ઉચ્ચ સ્તરની ભાષા લોકોને વાંચવા અને લખવા માટે સરળ હોય છે. Think Python એ પણ સમજાવે છે કે Python વિવિધ કમ્પ્યુટર પર ચાલી શકે છે.",
              kn: "ಉನ್ನತ ಮಟ್ಟದ ಭಾಷೆಯನ್ನು ಜನರು ಓದಲು ಮತ್ತು ಬರೆಯಲು ಸುಲಭ. Python ವಿವಿಧ ಕಂಪ್ಯೂಟರ್‌ಗಳಲ್ಲಿ ಕಾರ್ಯನಿರ್ವಹಿಸುತ್ತದೆ ಎಂದು Think Python ವಿವರಿಸುತ್ತದೆ.",
            }[language]
          : {
              hi: "दिए गए अंशों से इस प्रश्न के उत्तर की पुष्टि नहीं होती।",
              sa: "प्रदत्ताः पाठांशाः अस्य प्रश्नस्य उत्तरं न पुष्टयन्ति।",
              es: "Los pasajes proporcionados no confirman la respuesta a esta pregunta.",
              ta: "கொடுக்கப்பட்ட பகுதிகள் இந்தக் கேள்விக்கான பதிலை உறுதிப்படுத்தவில்லை.",
              te: "ఇచ్చిన పాఠ్య భాగాలు ఈ ప్రశ్నకు సమాధానాన్ని నిర్ధారించలేదు.",
              ml: "നൽകിയ ഭാഗങ്ങൾ ഈ ചോദ്യത്തിനുള്ള ഉത്തരം സ്ഥിരീകരിക്കുന്നില്ല.",
              bn: "দেওয়া অংশগুলো এই প্রশ্নের উত্তর নিশ্চিত করে না।",
              fr: "Les passages fournis ne confirment pas la réponse à cette question.",
              it: "I passaggi forniti non confermano la risposta a questa domanda.",
              gu: "આપેલા અંશો આ પ્રશ્નના જવાબની પુષ્ટિ કરતા નથી.",
              kn: "ಒದಗಿಸಿದ ಭಾಗಗಳು ಈ ಪ್ರಶ್ನೆಗೆ ಉತ್ತರವನ್ನು ದೃಢೀಕರಿಸುವುದಿಲ್ಲ.",
            }[language];
      }
      savedAnswers.set(cacheKey, clone(next));
      return next;
    },
  };
}

/** Tiny one-page PDF used only by the mock viewer when no upload is cached. */
export function mockPdfBytes(): Uint8Array {
  const text = `%PDF-1.1
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj
4 0 obj<< /Length 68 >>stream
BT /F1 18 Tf 72 720 Td (BookRAG mock PDF — not a live document) Tj ET
endstream
endobj
5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj
trailer<< /Root 1 0 R >>
%%EOF
`;
  return new TextEncoder().encode(text);
}
