"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { isMockMode, isLocalTestAuth, isSupabaseConfigured, mockEmail } from "@/lib/config";
import { createSupabaseBrowser } from "@/lib/auth/supabase";
import { isMockAccessToken, jwtShouldRefresh } from "@/lib/auth/token";
import {
  clearMockSession,
  readMockSession,
  writeMockSession,
  type BookragSession,
} from "@/lib/auth/session";

interface AuthContextValue {
  session: BookragSession | null;
  loading: boolean;
  supabaseReady: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<string | null>;
  signInGuest: () => Promise<void>;
  signOut: () => Promise<void>;
  getAccessToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function mockSessionFor(email: string): BookragSession {
  const id = "00000000-0000-4000-8000-000000000001";
  return {
    user: { id, email },
    accessToken: `mock.local.${id}`,
    source: "mock-local",
  };
}

function toSession(
  userId: string,
  email: string,
  accessToken: string,
  isAnonymous = false,
): BookragSession {
  return {
    user: { id: userId, email, isAnonymous },
    accessToken,
    source: "supabase",
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const supabaseReady = isSupabaseConfigured();
  const [session, setSession] = useState<BookragSession | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      if (supabaseReady) {
        const supabase = createSupabaseBrowser();
        if (!supabase) {
          if (!cancelled) setLoading(false);
          return;
        }
        const { data } = await supabase.auth.getSession();
        if (!cancelled && data.session) {
          setSession(
            toSession(data.session.user.id, data.session.user.email || "", data.session.access_token, data.session.user.is_anonymous),
          );
        }
        const { data: listener } = supabase.auth.onAuthStateChange((_event, next) => {
          if (!next) {
            setSession(null);
            return;
          }
          setSession(toSession(next.user.id, next.user.email || "", next.access_token, next.user.is_anonymous));
        });
        if (!cancelled) setLoading(false);
        return () => listener.subscription.unsubscribe();
      }
      const local = isMockMode() || isLocalTestAuth() ? readMockSession() : null;
      if (!cancelled) {
        setSession(local);
        setLoading(false);
      }
      return undefined;
    }
    const cleanup = boot();
    return () => {
      cancelled = true;
      void cleanup.then((fn) => fn?.());
    };
  }, [supabaseReady]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      if (supabaseReady) {
        const supabase = createSupabaseBrowser();
        if (!supabase) throw new Error("Supabase is not configured.");
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw new Error(error.message);
        return;
      }
      if (!isMockMode() && !isLocalTestAuth()) {
        throw new Error(
          "Supabase Auth is not configured. Add NEXT_PUBLIC_SUPABASE_URL and the anon key.",
        );
      }
      if (password.trim().length < 6) {
        throw new Error("Password must be at least 6 characters.");
      }
      const next = mockSessionFor(email.trim() || mockEmail());
      writeMockSession(next);
      setSession(next);
    },
    [supabaseReady],
  );

  const signUp = useCallback(
    async (email: string, password: string) => {
      if (supabaseReady) {
        const supabase = createSupabaseBrowser();
        if (!supabase) throw new Error("Supabase is not configured.");
        const { data, error } = await supabase.auth.signUp({ email, password });
        if (error) throw new Error(error.message);
        if (!data.session) {
          return "Check your email to confirm the account, then sign in.";
        }
        return null;
      }
      await signIn(email, password);
      return null;
    },
    [signIn, supabaseReady],
  );

  const signInGuest = useCallback(async () => {
    if (!supabaseReady) throw new Error("Guest access is unavailable right now.");
    const supabase = createSupabaseBrowser();
    if (!supabase) throw new Error("Guest access is unavailable right now.");
    const { data, error } = await supabase.auth.signInAnonymously();
    if (error) throw new Error(error.message);
    if (!data.session || !data.user) throw new Error("Guest session could not be created. Please try again.");
    setSession(toSession(data.user.id, "", data.session.access_token, true));
  }, [supabaseReady]);

  const signOut = useCallback(async () => {
    if (supabaseReady) {
      const supabase = createSupabaseBrowser();
      await supabase?.auth.signOut();
    }
    clearMockSession();
    setSession(null);
  }, [supabaseReady]);

  const getAccessToken = useCallback(async () => {
    if (supabaseReady) {
      const supabase = createSupabaseBrowser();
      if (!supabase) return null;
      const { data } = await supabase.auth.getSession();
      let token = data.session?.access_token ?? null;
      if (token && jwtShouldRefresh(token)) {
        const { data: refreshed } = await supabase.auth.refreshSession();
        token = refreshed.session?.access_token ?? token;
        if (refreshed.session) {
          setSession(
            toSession(refreshed.session.user.id, refreshed.session.user.email || "", token, refreshed.session.user.is_anonymous),
          );
        }
      }
      if (isMockAccessToken(token)) return null;
      return token;
    }
    if (!(isMockMode() || isLocalTestAuth())) return null;
    return session?.accessToken ?? readMockSession()?.accessToken ?? null;
  }, [session, supabaseReady]);

  const value = useMemo(
    () => ({
      session,
      loading,
      supabaseReady,
      signIn,
      signInGuest,
      signUp,
      signOut,
      getAccessToken,
    }),
    [getAccessToken, loading, session, signIn, signInGuest, signOut, signUp, supabaseReady],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
