export class BookragApiError extends Error {
  readonly code: string;
  readonly httpStatus: number;
  readonly retryable: boolean;

  constructor(message: string, code: string, httpStatus: number) {
    super(message);
    this.name = "BookragApiError";
    this.code = code;
    this.httpStatus = httpStatus;
    this.retryable = httpStatus === 429 || httpStatus === 503;
  }
}

const STATUS_CODES: Record<number, string> = {
  400: "invalid_input",
  401: "unauthenticated",
  403: "forbidden",
  404: "not_found",
  409: "still_processing",
  413: "payload_too_large",
  429: "usage_limited",
  503: "provider_unavailable",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

export function parseApiError(httpStatus: number, body: unknown): BookragApiError {
  const record = asRecord(body);
  const nested = asRecord(record?.error);
  const contractMessage = typeof nested?.message === "string" ? nested.message.trim() : "";
  const contractCode = typeof nested?.code === "string" ? nested.code.trim() : "";
  if (contractMessage) {
    return new BookragApiError(
      contractMessage,
      contractCode || STATUS_CODES[httpStatus] || "request_failed",
      httpStatus,
    );
  }

  // Codex FastAPI currently raises HTTPException(detail=string) in a few paths.
  const detail = record?.detail;
  if (typeof detail === "string" && detail.trim()) {
    return new BookragApiError(
      detail.trim(),
      STATUS_CODES[httpStatus] || "request_failed",
      httpStatus,
    );
  }

  const fallback =
    httpStatus === 401
      ? "Sign in to continue."
      : httpStatus === 413
        ? "That PDF is too large."
        : httpStatus === 429
          ? "Daily limit reached. Try again tomorrow."
          : httpStatus === 503
            ? "The answer service is temporarily unavailable."
            : "Something went wrong. Please try again.";
  return new BookragApiError(fallback, STATUS_CODES[httpStatus] || "request_failed", httpStatus);
}

export function errorMessage(err: unknown): string {
  if (err instanceof BookragApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return "Something went wrong. Please try again.";
}

export function isUnauthorized(err: unknown): boolean {
  return err instanceof BookragApiError && err.httpStatus === 401;
}
