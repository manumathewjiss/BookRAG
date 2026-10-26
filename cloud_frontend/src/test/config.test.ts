import { afterEach, describe, expect, it, vi } from "vitest";
import {
  assertPublicBrowserEnv,
  isLocalTestAuth,
  isMockMode,
  looksLikeServiceRoleKey,
  safeNextPath,
} from "@/lib/config";
import { isMockAccessToken, jwtShouldRefresh } from "@/lib/auth/token";

describe("production-safe config", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("keeps mock mode off unless explicitly enabled in development", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_BOOKRAG_USE_MOCK", "");
    expect(isMockMode()).toBe(false);
    vi.stubEnv("NEXT_PUBLIC_BOOKRAG_USE_MOCK", "true");
    expect(isMockMode()).toBe(true);
  });

  it("forces mock mode and local test auth off in production", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_BOOKRAG_USE_MOCK", "true");
    vi.stubEnv("NEXT_PUBLIC_BOOKRAG_LOCAL_TEST_AUTH", "true");
    expect(isMockMode()).toBe(false);
    expect(isLocalTestAuth()).toBe(false);
  });

  it("rejects open redirects", () => {
    expect(safeNextPath("/library")).toBe("/library");
    expect(safeNextPath("/chat/abc")).toBe("/chat/abc");
    expect(safeNextPath("https://evil.example/phish")).toBe("/library");
    expect(safeNextPath("//evil.example")).toBe("/library");
    expect(safeNextPath("/login")).toBe("/library");
    expect(safeNextPath("/libraryevil")).toBe("/library");
  });

  it("detects a service-role JWT so it never becomes the anon browser key", () => {
    const payload = Buffer.from(JSON.stringify({ role: "service_role" })).toString("base64url");
    const token = `eyJhbGciOiJub25lIn0.${payload}.sig`;
    expect(looksLikeServiceRoleKey(token)).toBe(true);
    const anon = `eyJhbGciOiJub25lIn0.${Buffer.from(JSON.stringify({ role: "anon" })).toString("base64url")}.sig`;
    expect(looksLikeServiceRoleKey(anon)).toBe(false);
  });

  it("never treats mock.local tokens as live API credentials", () => {
    expect(isMockAccessToken("mock.local.00000000-0000-4000-8000-000000000001")).toBe(true);
    expect(isMockAccessToken("eyJhbGciOiJIUzI1NiJ9.e30.sig")).toBe(false);
  });

  it("refuses a production build with mock mode enabled", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_BOOKRAG_USE_MOCK", "true");
    expect(() => assertPublicBrowserEnv()).toThrow(/USE_MOCK/);
  });

  it("refuses a service-role JWT as the public anon key", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_BOOKRAG_USE_MOCK", "false");
    const payload = Buffer.from(JSON.stringify({ role: "service_role" })).toString("base64url");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", `eyJhbGciOiJub25lIn0.${payload}.sig`);
    expect(() => assertPublicBrowserEnv()).toThrow(/anon\/public key/);
  });

  it("refuses secret Supabase keys and incomplete production configuration", () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_secret_private");
    expect(() => assertPublicBrowserEnv()).toThrow(/anon\/public key/);
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_publishable_public");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "");
    expect(() => assertPublicBrowserEnv()).toThrow(/NEXT_PUBLIC_SUPABASE_URL/);
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://sample.supabase.co");
    vi.stubEnv("NEXT_PUBLIC_BOOKRAG_API_URL", "http://sample.example");
    expect(() => assertPublicBrowserEnv()).toThrow(/public HTTPS origin/);
    vi.stubEnv("NEXT_PUBLIC_BOOKRAG_API_URL", "https://api.example");
    expect(() => assertPublicBrowserEnv()).not.toThrow();
  });

  it("refreshes JWTs inside the one-minute skew window", () => {
    const exp = Math.floor(Date.now() / 1000) + 30;
    const token = `hdr.${Buffer.from(JSON.stringify({ exp })).toString("base64url")}.sig`;
    expect(jwtShouldRefresh(token)).toBe(true);
  });
});
