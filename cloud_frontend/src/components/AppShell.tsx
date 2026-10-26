"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth/AuthProvider";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { session, loading, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !session) {
      const next = encodeURIComponent(pathname || "/library");
      router.replace(`/login?next=${next}`);
    }
  }, [loading, pathname, router, session]);

  if (loading) {
    return (
      <div className="page">
        <p className="status pulse">Restoring your session…</p>
      </div>
    );
  }
  if (!session) return null;

  async function onLogout() {
    await signOut();
    router.replace("/login");
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" href="/library">
          BookRAG
        </Link>
        <nav className="top-nav" aria-label="Main">
          <Link href="/library" aria-current={pathname.startsWith("/library") ? "page" : undefined}>
            Library
          </Link>
          <span className="user-meta" title={session.user.email}>
            {session.user.email}
          </span>
          <button type="button" className="ghost" onClick={() => void onLogout()}>
            Log out
          </button>
        </nav>
      </header>
      {children}
    </div>
  );
}
