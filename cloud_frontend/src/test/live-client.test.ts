import { beforeEach, describe, expect, it, vi } from "vitest";
import { createLiveClient } from "@/lib/api/client";

describe("live API client", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const headers = new Headers(init?.headers);
        if (!headers.get("Authorization")?.startsWith("Bearer ")) {
          return new Response(JSON.stringify({ error: { code: "unauthenticated", message: "Sign in" } }), {
            status: 401,
          });
        }
        if (url.endsWith("/api/v1/me")) {
          return Response.json({
            user_id: "user-1",
            daily_questions_used: 2,
            daily_uploads_used: 1,
          });
        }
        if (url.endsWith("/api/v1/documents/doc-1/pdf")) {
          return new Response(new Uint8Array([37, 80, 68, 70, 45]), {
            headers: { "content-type": "application/pdf" },
          });
        }
        if (url.includes("/api/v1/documents/doc-1") && init?.method === "DELETE") {
          return new Response(null, { status: 204 });
        }
        if (url.includes("/api/v1/documents/gone") && init?.method === "DELETE") {
          return new Response(null, { status: 404 });
        }
        if (url.endsWith("/api/v1/documents") && init?.method === "POST") {
          return new Response(
            JSON.stringify({
              document: {
                id: "doc-1",
                title: "Paper",
                filename: "paper.pdf",
                status: "queued",
                page_count: 0,
                passage_count: 0,
                error: null,
                created_at: "2026-10-24T00:00:00Z",
                updated_at: "2026-10-24T00:00:00Z",
              },
            }),
            { status: 202 },
          );
        }
        return new Response("missing", { status: 404 });
      }),
    );
  });

  it("sends the Bearer token and never a user id", async () => {
    const client = createLiveClient(async () => "test-token");
    const me = await client.me();
    expect(me.user_id).toBe("user-1");
    const call = vi.mocked(fetch).mock.calls[0];
    const headers = new Headers(call[1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer test-token");
    expect(JSON.stringify(call[1])).not.toMatch(/user_id/);
  });

  it("treats 202 upload as success", async () => {
    const client = createLiveClient(async () => "test-token");
    const file = new File([new Uint8Array([1, 2, 3])], "paper.pdf", { type: "application/pdf" });
    const doc = await client.uploadDocument(file);
    expect(doc.status).toBe("queued");
    expect(doc.id).toBe("doc-1");
  });

  it("downloads a private PDF with the bearer token and no browser cache", async () => {
    const client = createLiveClient(async () => "test-token");
    expect(new TextDecoder().decode(await client.getPdf("doc-1"))).toBe("%PDF-");
    const call = vi.mocked(fetch).mock.calls[0];
    expect(new Headers(call[1]?.headers).get("Authorization")).toBe("Bearer test-token");
    expect(call[1]?.cache).toBe("no-store");
  });

  it("treats DELETE 204 as success", async () => {
    const client = createLiveClient(async () => "test-token");
    await expect(client.deleteDocument("doc-1")).resolves.toBeUndefined();
  });

  it("treats DELETE 404 as already gone", async () => {
    const client = createLiveClient(async () => "test-token");
    await expect(client.deleteDocument("gone")).resolves.toBeUndefined();
  });

  it("refuses to send a mock.local token to the live API", async () => {
    const client = createLiveClient(async () => "mock.local.not-a-session");
    await expect(client.me()).rejects.toMatchObject({ httpStatus: 401, code: "unauthenticated" });
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });
});
