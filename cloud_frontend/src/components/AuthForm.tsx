"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { isLocalTestAuth, isMockMode, isSupabaseConfigured } from "@/lib/config";

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const { signIn, signUp } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

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
      router.replace("/library");
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
            ? "Accounts are stored in Supabase Auth."
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
        {error ? <p className="error-card">{error}</p> : null}
        {notice ? <p className="empty">{notice}</p> : null}
        <div className="auth-actions">
          <button className="primary" type="submit" disabled={busy}>
            {busy ? "Working…" : mode === "login" ? "Sign in" : "Sign up"}
          </button>
          {mode === "login" ? (
            <p>
              Need an account? <Link href="/signup">Sign up</Link>
            </p>
          ) : (
            <p>
              Already registered? <Link href="/login">Sign in</Link>
            </p>
          )}
        </div>
      </form>
    </div>
  );
}
