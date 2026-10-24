import { describe, expect, it } from "vitest";
import { parseApiError } from "@/lib/api/errors";

describe("parseApiError", () => {
  it("reads the Codex contract error object", () => {
    const err = parseApiError(409, {
      error: { code: "still_processing", message: "This PDF is still being indexed." },
    });
    expect(err.code).toBe("still_processing");
    expect(err.httpStatus).toBe(409);
    expect(err.message).toBe("This PDF is still being indexed.");
    expect(err.retryable).toBe(false);
  });

  it("accepts FastAPI detail strings as a compatibility fallback", () => {
    const err = parseApiError(401, { detail: "Sign in to continue" });
    expect(err.code).toBe("unauthenticated");
    expect(err.message).toBe("Sign in to continue");
  });

  it("marks 429 and 503 as retryable", () => {
    expect(parseApiError(429, null).retryable).toBe(true);
    expect(parseApiError(503, null).retryable).toBe(true);
    expect(parseApiError(400, null).retryable).toBe(false);
  });
});
