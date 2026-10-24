export const MIN_QUESTION_CHARS = 8;
export const MAX_QUESTION_CHARS = 1200;
export const MAX_PDF_BYTES = 25 * 1024 * 1024;
export const DOCUMENT_POLL_MS = 1500;
export const DAILY_UPLOAD_LIMIT = 5;
export const DAILY_QUESTION_LIMIT = 50;

export function apiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_BOOKRAG_API_URL || "http://localhost:8000").replace(/\/$/, "");
}

export function isMockMode(): boolean {
  const raw = (process.env.NEXT_PUBLIC_BOOKRAG_USE_MOCK || "true").trim().toLowerCase();
  return raw !== "false" && raw !== "0" && raw !== "off";
}

/** Enables fake login only for a local integration server; never in a production build. */
export function isLocalTestAuth(): boolean {
  return process.env.NODE_ENV !== "production" &&
    process.env.NEXT_PUBLIC_BOOKRAG_LOCAL_TEST_AUTH === "true";
}

export function supabaseUrl(): string {
  return (process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
}

export function supabaseAnonKey(): string {
  return (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "").trim();
}

export function isSupabaseConfigured(): boolean {
  const url = supabaseUrl();
  const key = supabaseAnonKey();
  if (!url || !key) return false;
  if (url.includes("YOUR_PROJECT")) return false;
  if (key.includes("replace-with")) return false;
  return true;
}

export function mockEmail(): string {
  return (process.env.NEXT_PUBLIC_BOOKRAG_MOCK_EMAIL || "demo@bookrag.local").trim();
}
