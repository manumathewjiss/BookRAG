import Link from "next/link";

export default function HomePage() {
  return (
    <div className="landing">
      <header className="landing-header">
        <Link className="landing-brand" href="/" aria-label="BookRAG home">Book<span>RAG</span></Link>
        <nav aria-label="Account">
          <Link className="landing-signin" href="/login">Sign in</Link>
          <Link className="landing-header-cta" href="/signup">Create an account <span aria-hidden="true">→</span></Link>
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
              <Link className="landing-primary" href="/signup">Create an account <span aria-hidden="true">→</span></Link>
              <Link className="landing-secondary" href="/login">I already have an account</Link>
            </div>
            <p className="landing-assurance">Your PDFs are visible only to you. Answers are tied to cited passages.</p>
          </div>

          <div className="landing-preview" aria-label="Example of a cited answer in BookRAG">
            <div className="preview-topline"><span className="preview-dots" aria-hidden="true">•••</span><span>Inside your library</span></div>
            <div className="preview-book"><span className="preview-book-icon" aria-hidden="true">▤</span><span><strong>Your document</strong><small>Ready to explore</small></span></div>
            <div className="preview-question"><small>YOUR QUESTION</small><p>What does this document say about the main finding?</p></div>
            <div className="preview-answer"><small>ANSWER</small><p>BookRAG explains the finding using the text in your document.</p></div>
            <div className="preview-citation"><span className="preview-citation-mark" aria-hidden="true">↗</span><span><strong>Check the source</strong><small>Open the cited PDF page and passage</small></span><span aria-hidden="true">→</span></div>
          </div>
        </section>

        <section className="landing-steps" aria-label="How BookRAG works">
          <div><span>01</span><h2>Add a PDF</h2><p>Bring a digital-text document into your private library.</p></div>
          <div><span>02</span><h2>Ask naturally</h2><p>Explore its contents with questions in your own words.</p></div>
          <div><span>03</span><h2>Read with confidence</h2><p>Check supporting passages against the original pages.</p></div>
        </section>
      </main>

      <footer className="landing-footer"><span>BookRAG</span><span>Read closely. Ask freely. Verify the source.</span></footer>
    </div>
  );
}
