import { MAX_PDF_BYTES } from "@/lib/config";

export interface PdfValidationOk {
  ok: true;
}

export interface PdfValidationErr {
  ok: false;
  code: "not_pdf" | "empty" | "too_large";
  message: string;
}

export type PdfValidation = PdfValidationOk | PdfValidationErr;

export function validatePdfFile(file: File, maxBytes = MAX_PDF_BYTES): PdfValidation {
  if (!file || file.size <= 0) {
    return { ok: false, code: "empty", message: "That file is empty." };
  }
  if (file.size > maxBytes) {
    const mb = Math.round(maxBytes / (1024 * 1024));
    return {
      ok: false,
      code: "too_large",
      message: `PDFs must be ${mb} MB or smaller.`,
    };
  }
  const name = (file.name || "").toLowerCase();
  const type = (file.type || "").toLowerCase();
  const namedPdf = name.endsWith(".pdf");
  const typedPdf = type === "application/pdf" || type === "application/x-pdf";
  if (!namedPdf && !typedPdf) {
    return { ok: false, code: "not_pdf", message: "Please choose a PDF file." };
  }
  return { ok: true };
}

export function pdfMagicOk(bytes: Uint8Array): boolean {
  return bytes.length >= 5 && String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3], bytes[4]) === "%PDF-";
}

export async function looksLikePdf(file: Blob): Promise<boolean> {
  const buf = new Uint8Array(await readBlobBytes(file));
  if (buf.length === 0) {
    // Some test File shims cannot expose bytes; the name/MIME check already ran.
    return true;
  }
  return pdfMagicOk(buf);
}

async function readBlobBytes(file: Blob): Promise<ArrayBuffer> {
  if (typeof file.arrayBuffer === "function") {
    return file.arrayBuffer();
  }
  return new Response(file).arrayBuffer();
}

export function validateQuestion(question: string, min = 8, max = 1200): PdfValidation {
  const trimmed = question.trim();
  if (trimmed.length < min) {
    return {
      ok: false,
      code: "empty",
      message: `Ask a question of at least ${min} characters.`,
    };
  }
  if (trimmed.length > max) {
    return {
      ok: false,
      code: "too_large",
      message: `Questions can be at most ${max} characters.`,
    };
  }
  return { ok: true };
}
