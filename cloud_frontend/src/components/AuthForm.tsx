"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { isLocalTestAuth, isMockMode, isSupabaseConfigured, safeNextPath } from "@/lib/config";
import { GuestAccessButton } from "@/components/GuestAccessButton";

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const { signIn, signUp, session, loading } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = safeNextPath(searchParams.get("next"));
  const expired = searchParams.get("reason") === "expired";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(expired ? "Your session ended. Sign in again." : "");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && session) router.replace(nextPath);
  }, [loading, nextPath, router, session]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      if (mode === "signup") {
        const message = await signUp(email, password);
        if (message) {
          setNotice(message);
          return;
        }
      } else {
        await signIn(email, password);
      }
      router.replace(nextPath);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not continue.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={onSubmit}>
        <Link className="brand" href="/">
          BookRAG
        </Link>
        <h1>{mode === "login" ? "Sign in" : "Create an account"}</h1>
        <p>
          Private PDF library and RAG chat.{" "}
          {isSupabaseConfigured()
            ? "Accounts are stored in Supabase Auth. The API receives only your access token."
            : isMockMode()
              ? "Supabase is not configured, so this local session is mock-only."
              : isLocalTestAuth()
                ? "This is a local integration test with simulated sign-in. No cloud account is used."
              : "Add NEXT_PUBLIC_SUPABASE_URL and the anon key to enable Auth."}
        </p>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error ? (
          <p className="error-card" role="alert">
            {error}
          </p>
        ) : null}
        {notice ? <p className="empty">{notice}</p> : null}
        <div className="auth-actions">
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Working…" : mode === "login" ? "Sign in" : "Sign up"}
          </button>
          {mode === "login" ? (
            <p>
              Need an account?{" "}
              <Link href={`/signup?next=${encodeURIComponent(nextPath)}`}>Sign up</Link>
            </p>
          ) : (
            <p>
              Already registered?{" "}
              <Link href={`/login?next=${encodeURIComponent(nextPath)}`}>Sign in</Link>
            </p>
          )}
        </div>
        {isSupabaseConfigured() && (
          <div className="auth-guest-option">
            <span>or</span>
            <GuestAccessButton nextPath={nextPath} className="guest-secondary" />
            <p>No email needed. Keep this browser’s site data to return to your guest library.</p>
          </div>
        )}
      </form>
    </div>
  );
}
