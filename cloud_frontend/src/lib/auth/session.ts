export interface BookragUser {
  id: string;
  email: string;
}

export interface BookragSession {
  user: BookragUser;
  accessToken: string;
  source: "supabase" | "mock-local";
}

const MOCK_KEY = "bookrag.mock.session";

export function readMockSession(): BookragSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(MOCK_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as BookragSession;
    if (!parsed?.user?.id || !parsed.accessToken) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeMockSession(session: BookragSession): void {
  window.localStorage.setItem(MOCK_KEY, JSON.stringify(session));
}

export function clearMockSession(): void {
  window.localStorage.removeItem(MOCK_KEY);
}
