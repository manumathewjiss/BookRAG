"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { AskIcon } from "@/components/AskIcon";

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
      <aside className="sidebar">
        <div>
          <Link className="brand" href="/library" aria-label="BookRAG library">
            Book<span>RAG</span>
          </Link>
          <p className="brand-subtitle">Your books.<br />Deeper answers.</p>
          <nav className="side-nav" aria-label="Main">
            <Link href="/library" aria-current={pathname.startsWith("/library") ? "page" : undefined}>
              <span aria-hidden="true">▤</span> Library
            </Link>
            {pathname.startsWith("/chat/") ? (
              <span className="side-nav-current"><span className="side-nav-icon"><AskIcon /></span> Ask</span>
            ) : null}
          </nav>
        </div>
        <div className="sidebar-account">
          <span className="user-meta" title={session.user.email}>{session.user.email}</span>
          <button type="button" className="sidebar-logout" onClick={() => void onLogout()}>
            Log out
          </button>
        </div>
      </aside>
      <div className="shell-content">
        <header className="mobile-topbar">
          <Link className="brand" href="/library">Book<span>RAG</span></Link>
          <Link href="/library">Library</Link>
          <button type="button" aria-label="Mobile sign out" onClick={() => void onLogout()}>Log out</button>
        </header>
        {children}
      </div>
    </div>
  );
}
