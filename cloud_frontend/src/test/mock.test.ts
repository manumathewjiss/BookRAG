import { afterEach, describe, expect, it, vi } from "vitest";
import { BookragApiError } from "@/lib/api/errors";
import { createMockClient, resetMockClient } from "@/lib/api/mock";

describe("mock BookRAG client", () => {
  afterEach(() => {
    vi.useRealTimers();
    resetMockClient();
  });

  it("lists seed documents and refuses ungrounded questions", async () => {
    const client = createMockClient();
    expect(client.mode).toBe("mock");
    const docs = await client.listDocuments();
    expect(docs.length).toBeGreaterThan(0);
    const ready = docs.find((d) => d.status === "ready");
    expect(ready).toBeTruthy();
    const refusal = await client.chat(ready!.id, "What is Arjuna’s email address today?");
    expect(refusal.enough_evidence).toBe(false);
    expect(refusal.evidence_status).toBe("absent");
    expect(refusal.citations).toEqual([]);
  });

  it("returns citations for a grounded question", async () => {
    const client = createMockClient();
    const docs = await client.listDocuments();
    const ready = docs.find((d) => d.status === "ready")!;
    const answer = await client.chat(ready.id, "What is a high-level language in this book?");
    expect(answer.enough_evidence).toBe(true);
    expect(answer.citations[0]?.pdf_page).toBe(23);
    expect(answer.citations[0]?.excerpt.length).toBeGreaterThan(20);
  });

  it("serves private mock PDF bytes without a live token", async () => {
    const client = createMockClient();
    const docs = await client.listDocuments();
    const ready = docs.find((d) => d.status === "ready")!;
    const bytes = new Uint8Array(await client.getPdf(ready.id));
    expect(String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3], bytes[4])).toBe("%PDF-");
  });

  it("returns unverified evidence when Sol would claim support without a citation", async () => {
    const client = createMockClient();
    const docs = await client.listDocuments();
    const ready = docs.find((d) => d.status === "ready")!;
    const answer = await client.chat(ready.id, "Please give an unverified answer now");
    expect(answer.evidence_status).toBe("unverified");
    expect(answer.citations).toEqual([]);
  });

  it("rejects chat while a document is still processing", async () => {
    const client = createMockClient();
    const docs = await client.listDocuments();
    const processing = docs.find((d) => d.status === "processing");
    expect(processing).toBeTruthy();
    await expect(client.chat(processing!.id, "What is a high-level language?")).rejects.toBeInstanceOf(
      BookragApiError,
    );
  });

  it("uploads a PDF and reports queued then ready", async () => {
    vi.useFakeTimers();
    const client = createMockClient();
    const pdf = new File([new TextEncoder().encode("%PDF-1.4 mock")], "notes.pdf", {
      type: "application/pdf",
    });
    const created = await client.uploadDocument(pdf);
    expect(created.status).toBe("queued");
    await vi.advanceTimersByTimeAsync(2000);
    const later = await client.getDocument(created.id);
    expect(later.status).toBe("ready");
  });
});
