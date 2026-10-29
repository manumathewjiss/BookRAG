import { decodeJwtPayload } from "@/lib/config";

export function isMockAccessToken(token: string | null | undefined): boolean {
  return Boolean(token && token.startsWith("mock.local."));
}

export function jwtExpiresAt(token: string): number | null {
  try {
    const payload = decodeJwtPayload(token.split(".")[1] || "");
    return typeof payload.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
}

export function jwtShouldRefresh(token: string, skewMs = 60_000): boolean {
  const exp = jwtExpiresAt(token);
  if (!exp) return false;
  return exp * 1000 - Date.now() < skewMs;
}
