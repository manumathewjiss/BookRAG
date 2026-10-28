"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth/AuthProvider";

export default function HomePage() {
  const { session, loading } = useAuth();
  const destination = session ? "/library" : "/signup";
  const actionLabel = session ? "Open my library" : "Create an account";

  return (
    <div className="landing">
      <header className="landing-header">
        <Link className="landing-brand" href="/" aria-label="BookRAG home">Book<span>RAG</span></Link>
        <nav aria-label="Account">
          {!loading && <Link className="landing-signin" href={session ? "/library" : "/login"}>{session ? "My library" : "Sign in"}</Link>}
        </nav>
      </header>

      <main className="landing-main">
        <section className="landing-hero" aria-labelledby="landing-title">
          <div className="landing-copy">
            <p className="landing-kicker"><span aria-hidden="true" /> A reading companion for your PDFs</p>
            <h1 id="landing-title">Find the answer.<br /><em>See the page.</em></h1>
            <p className="landing-intro">
              Keep your documents in a private library. Ask a question, get a clear answer,
              and open the original PDF page behind it.
            </p>
            <div className="landing-actions">
              {!loading && <Link className="landing-primary" href={destination}>{actionLabel} <span aria-hidden="true">→</span></Link>}
            </div>
            <p className="landing-assurance">Private documents. Answers you can check against the original page.</p>
          </div>
        </section>
      </main>

      <footer className="landing-footer"><span>BookRAG</span><span>Read closely. Ask freely. Verify the source.</span></footer>
    </div>
  );
}
