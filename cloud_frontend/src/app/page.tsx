import Link from "next/link";

export default function HomePage() {
  return (
    <div className="page">
      <section className="hero">
        <p className="doc-tag">Private PDF library</p>
        <h1>BookRAG</h1>
        <p>
          Upload your own PDFs, ask questions, and read answers with clickable citations: filename,
          PDF page, and supporting excerpt. The model may refuse when the selected document does not
          contain the answer.
        </p>
        <p>
          <Link className="primary" href="/login" style={{ display: "inline-block" }}>
            Sign in
          </Link>
        </p>
      </section>
    </div>
  );
}
