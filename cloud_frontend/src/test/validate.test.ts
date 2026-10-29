import { describe, expect, it } from "vitest";
import { looksLikePdf, pdfMagicOk, validatePdfFile, validateQuestion } from "@/lib/pdf/validate";

function file(name: string, bytes: number, type = "application/pdf"): File {
  return new File([new Uint8Array(bytes)], name, { type });
}

describe("validatePdfFile", () => {
  it("rejects empty and oversized files", () => {
    expect(validatePdfFile(file("a.pdf", 0)).ok).toBe(false);
    const oversized = validatePdfFile(file("a.pdf", 26 * 1024 * 1024));
    expect(oversized.ok).toBe(false);
    if (!oversized.ok) expect(oversized.code).toBe("too_large");
  });

  it("requires a PDF name or MIME type", () => {
    expect(validatePdfFile(file("notes.txt", 12, "text/plain")).ok).toBe(false);
    expect(validatePdfFile(file("paper.pdf", 12)).ok).toBe(true);
  });
});

describe("pdf magic header", () => {
  it("accepts %PDF- and rejects other bytes", () => {
    expect(pdfMagicOk(new TextEncoder().encode("%PDF-1.4 rest"))).toBe(true);
    expect(pdfMagicOk(new TextEncoder().encode("notpdf"))).toBe(false);
  });

  it("does not throw on a File shim", async () => {
    const file = new File([new Uint8Array([1, 2, 3])], "a.pdf", { type: "application/pdf" });
    await expect(looksLikePdf(file)).resolves.toBeTypeOf("boolean");
  });
});

describe("validateQuestion", () => {
  it("enforces the 8–1200 character contract", () => {
    expect(validateQuestion("short").ok).toBe(false);
    expect(validateQuestion("What is a high-level language?").ok).toBe(true);
    expect(validateQuestion("x".repeat(1201)).ok).toBe(false);
  });
});
