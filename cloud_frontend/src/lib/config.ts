export const MIN_QUESTION_CHARS = 8;
export const MAX_QUESTION_CHARS = 1200;
export const MAX_PDF_BYTES = 25 * 1024 * 1024;
export const DOCUMENT_POLL_MS = 1500;
export const DAILY_UPLOAD_LIMIT = 5;
export const DAILY_QUESTION_LIMIT = 50;

export function apiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_BOOKRAG_API_URL || "http://localhost:8000").replace(/\/$/, "");
}

function flag(value: string | undefined): string {
  return (value || "").trim().toLowerCase();
}

function isEnabled(value: string | undefined): boolean {
  const raw = flag(value);
  return raw === "true" || raw === "1" || raw === "on";
}

export function isProductionBuild(): boolean {
  return process.env.NODE_ENV === "production" || process.env.VERCEL_ENV === "production";
}

/**
 * Isolated in-browser API. Always off in production builds, even if the public
 * env var is mistakenly set on Vercel.
 */
export function isMockMode(): boolean {
  if (isProductionBuild()) return false;
  return isEnabled(process.env.NEXT_PUBLIC_BOOKRAG_USE_MOCK);
}

/** Enables fake login only for a local integration server; never in a production build. */
export function isLocalTestAuth(): boolean {
  if (isProductionBuild()) return false;
  return isEnabled(process.env.NEXT_PUBLIC_BOOKRAG_LOCAL_TEST_AUTH);
}

export function supabaseUrl(): string {
  return (process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
}

export function supabaseAnonKey(): string {
  return (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "").trim();
}

export function assertPublicBrowserEnv(): void {
  if (isProductionBuild()) {
    if (isEnabled(process.env.NEXT_PUBLIC_BOOKRAG_USE_MOCK)) {
      throw new Error("NEXT_PUBLIC_BOOKRAG_USE_MOCK cannot be enabled for a production build.");
    }
    if (isEnabled(process.env.NEXT_PUBLIC_BOOKRAG_LOCAL_TEST_AUTH)) {
      throw new Error("NEXT_PUBLIC_BOOKRAG_LOCAL_TEST_AUTH cannot be enabled for a production build.");
    }
  }
  if (looksLikeServiceRoleKey(supabaseAnonKey())) {
    throw new Error("NEXT_PUBLIC_SUPABASE_ANON_KEY must be the anon/public key, not a service-role JWT.");
  }
  for (const [name, value] of Object.entries(process.env)) {
    if (!name.startsWith("NEXT_PUBLIC_")) continue;
    const blob = `${name}=${value || ""}`;
    if (/SERVICE_ROLE|VOYAGE_API_KEY|OPENAI_API_KEY|SUPABASE_SERVICE/i.test(blob)) {
      throw new Error(`${name} must not carry a private backend secret into the browser bundle.`);
    }
  }
}

export function looksLikeServiceRoleKey(key: string): boolean {
  const trimmed = key.trim();
  if (!trimmed) return false;
  if (/service_role|supabase_admin/i.test(trimmed)) return true;
  const parts = trimmed.split(".");
  if (parts.length < 2) return false;
  try {
    const json = decodeJwtPayload(parts[1]);
    const role = typeof json.role === "string" ? json.role : "";
    return role === "service_role" || role === "supabase_admin";
  } catch {
    return false;
  }
}

export function decodeJwtPayload(segment: string): Record<string, unknown> {
  const padded = segment.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((segment.length + 3) % 4);
  const json = typeof atob === "function"
    ? atob(padded)
    : Buffer.from(padded, "base64").toString("utf8");
  return JSON.parse(json) as Record<string, unknown>;
}

export function isSupabaseConfigured(): boolean {
  const url = supabaseUrl();
  const key = supabaseAnonKey();
  if (!url || !key) return false;
  if (url.includes("YOUR_PROJECT")) return false;
  if (key.includes("replace-with")) return false;
  if (looksLikeServiceRoleKey(key)) return false;
  return true;
}

export function mockEmail(): string {
  return (process.env.NEXT_PUBLIC_BOOKRAG_MOCK_EMAIL || "demo@bookrag.local").trim();
}

/** Only in-app paths under /library or /chat; blocks open redirects. */
export function safeNextPath(raw: string | null | undefined): string {
  if (!raw) return "/library";
  if (!raw.startsWith("/")) return "/library";
  if (raw.startsWith("//") || raw.includes("://") || raw.includes("\\")) return "/library";
  if (raw.startsWith("/library") || raw.startsWith("/chat")) return raw;
  return "/library";
}
