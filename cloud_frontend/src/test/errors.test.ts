import { describe, expect, it } from "vitest";
import { isUnauthorized, parseApiError } from "@/lib/api/errors";

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

  it("maps 403 to forbidden rather than a CORS/origin code", () => {
    const err = parseApiError(403, { error: { code: "forbidden", message: "Not allowed." } });
    expect(err.code).toBe("forbidden");
    expect(err.code).not.toBe("forbidden_origin");
  });

  it("detects expired sessions from 401", () => {
    expect(isUnauthorized(parseApiError(401, { detail: "Sign in to continue" }))).toBe(true);
    expect(isUnauthorized(parseApiError(404, null))).toBe(false);
  });
});
