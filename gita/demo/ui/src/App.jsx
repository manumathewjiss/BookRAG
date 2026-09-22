import { useEffect, useMemo, useRef, useState } from "react";

const API = "";

// Always available even if /api/health fails (so Ask + chips still work).
const FALLBACK_SAMPLES = [
  "What does Bhagavad Gita 2.47 say?",
  "According to Bhagavad Gita 18.66, what does Krishna tell Arjuna to surrender, and what does He promise?",
  "If a person offers Krishna something as simple as a leaf or a little water, but with love, does the Gita say He accepts it?",
  "In what way can a person’s own mind be their friend, and in what way can it be their enemy?",
  "What example does the commentary give of a king whose last thought was an animal, and what body did he get next?",
  "How does this Gita distinguish sannyasa, the renounced order, from tyaga, renunciation?",
];

function scorePct(score) {
  if (score == null || Number.isNaN(score)) return null;
  return Math.max(0, Math.min(100, Math.round(Number(score) * 100)));
}

function StepCard({ step, index, active }) {
  return (
    <article className={`step-card ${active ? "active" : ""}`}>
      <div className="step-index">{index + 1}</div>
      <div className="step-body">
        <h3>{step.title}</h3>
        <p className="step-simple">{step.simple}</p>
        {step.elapsed_ms != null && (
          <p className="step-meta">{step.elapsed_ms} ms</p>
        )}
      </div>
    </article>
  );
}

function HitCard({ hit, expanded, onToggle }) {
  const pct = scorePct(hit.score);
  return (
    <article className="hit-card">
      <button type="button" className="hit-header" onClick={onToggle}>
        <div>
          <span className="rank">#{hit.rank}</span>
          <strong>{hit.source_record_id}</strong>
          <span className="section-pill">{hit.section}</span>
        </div>
        <div className="hit-right">
          {pct != null && (
            <span className="score" title="≈ cosine similarity × 100">
              {pct}% match
            </span>
          )}
          <span className="chevron">{expanded ? "▾" : "▸"}</span>
        </div>
      </button>
      {pct != null && (
        <div className="score-bar" aria-hidden="true">
          <span style={{ width: `${pct}%` }} />
        </div>
      )}
      <p className="hit-preview">{hit.body_preview}</p>
      {expanded && <pre className="hit-full">{hit.text}</pre>}
      <p className="hit-meta">
        chunk <code>{hit.chunk_id}</code>
        {hit.page_start != null && (
          <>
            {" "}
            · PDF pp. {hit.page_start}
            {hit.page_end != null && hit.page_end !== hit.page_start
              ? `–${hit.page_end}`
              : ""}
          </>
        )}
      </p>
    </article>
  );
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [warming, setWarming] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [expandedHits, setExpandedHits] = useState({});
  const [showPrompt, setShowPrompt] = useState(false);
  const [activeStep, setActiveStep] = useState(0);
  const abortRef = useRef(null);

  useEffect(() => {
    fetch(`${API}/api/health`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`health ${r.status}`);
        return r.json();
      })
      .then(setHealth)
      .catch(() =>
        setHealth({
          status: "degraded",
          ollama_reachable: false,
          artifacts: { faiss_index: false },
          sample_questions: FALLBACK_SAMPLES,
          note: "Could not reach /api/health. Sample chips still work if the API is up.",
        })
      );
  }, []);

  useEffect(() => {
    if (!result?.pipeline_steps?.length) return undefined;
    setActiveStep(0);
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setActiveStep(Math.min(i, result.pipeline_steps.length - 1));
      if (i >= result.pipeline_steps.length - 1) clearInterval(id);
    }, 280);
    return () => clearInterval(id);
  }, [result]);

  const samples = useMemo(() => {
    const fromApi = health?.sample_questions;
    return fromApi && fromApi.length ? fromApi : FALLBACK_SAMPLES;
  }, [health]);

  async function warmup() {
    setWarming(true);
    setError("");
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 20000);
      const res = await fetch(`${API}/api/warmup`, {
        method: "POST",
        signal: controller.signal,
      });
      clearTimeout(timer);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Warmup failed");
      setHealth((h) => ({
        ...h,
        retriever_loaded: true,
        ollama_reachable: data.ollama_reachable,
      }));
    } catch (e) {
      const msg =
        e.name === "AbortError"
          ? "Warmup timed out. For the demo, click a sample question instead (instant replay)."
          : String(e.message || e);
      setError(msg);
    } finally {
      setWarming(false);
    }
  }

  async function ask(q) {
    const text = (q ?? question).trim();
    if (!text) {
      setError("Type a question or click a sample chip below.");
      return;
    }
    if (loading) return;

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setQuestion(text);
    setLoading(true);
    setError("");
    setResult(null);
    setExpandedHits({});
    setShowPrompt(false);
    setActiveStep(0);

    const timer = setTimeout(() => controller.abort(), 250000);
    try {
      const res = await fetch(`${API}/api/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text, top_k: 5 }),
        signal: controller.signal,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail =
          typeof data.detail === "string"
            ? data.detail
            : JSON.stringify(data.detail || data);
        throw new Error(detail || `Request failed (${res.status})`);
      }
      if (!data.answer) {
        throw new Error("API returned no answer. Is the demo API running on port 8000?");
      }
      setResult(data);
      setActiveStep((data.pipeline_steps || []).length - 1);
    } catch (e) {
      const msg =
        e.name === "AbortError"
          ? "Request timed out. Click a sample question for an instant saved-eval demo, or restart the API (./run_api.sh)."
          : String(e.message || e);
      setError(msg);
    } finally {
      clearTimeout(timer);
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <div className="bg-wash" aria-hidden="true" />

      <header className="top">
        <div>
          <p className="eyebrow">Professor demo · frozen local stack</p>
          <h1>Bhagavad Gita RAG</h1>
          <p className="lede">
            Ask in English. The system retrieves Top-5 book passages with E5 +
            FAISS, then Qwen2.5 3B answers only from that evidence.
          </p>
        </div>
        <div className="status-panel">
          <div className={`pill ${health?.ollama_reachable ? "ok" : "warn"}`}>
            Ollama {health?.ollama_reachable ? "online" : "offline"}
          </div>
          <div className={`pill ${health?.artifacts?.faiss_index ? "ok" : "warn"}`}>
            FAISS {health?.artifacts?.faiss_index ? "ready" : "missing"}
          </div>
          <button type="button" className="ghost-btn" onClick={warmup} disabled={warming}>
            {warming ? "Loading E5…" : health?.retriever_loaded ? "E5 loaded" : "Warm up E5"}
          </button>
        </div>
      </header>

      <section className="ask-panel">
        <label htmlFor="q">English question</label>
        <div className="ask-row">
          <textarea
            id="q"
            rows={3}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Click a sample below, or type e.g. What does Bhagavad Gita 2.47 say?"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                ask();
              }
            }}
          />
          <button
            type="button"
            className="ask-btn"
            disabled={loading}
            onClick={() => ask()}
          >
            {loading ? "Running…" : "Ask"}
          </button>
        </div>
        <p className="muted tip">
          Tip: click a <strong>sample question</strong> for an instant answer. Custom
          live questions need Ollama + the Python worker and can take longer.
        </p>
        <div className="samples">
          {samples.map((s) => (
            <button key={s} type="button" className="sample" onClick={() => ask(s)} disabled={loading}>
              {s}
            </button>
          ))}
        </div>
        {error && <p className="error">{error}</p>}
      </section>

      {loading && (
        <section className="live-strip">
          <div className="spinner" />
          <div>
            <strong>Running the frozen pipeline…</strong>
            <p>query: prefix → E5 vector → FAISS Top-5 → evidence prompt → Qwen2.5 3B</p>
          </div>
        </section>
      )}

      {result && (
        <div className="results">
          <section className="answer-card">
            <div className="answer-head">
              <h2>Answer</h2>
              <div className="answer-badges">
                {result.demo_mode === "replay_saved_eval" && (
                  <span className="pill ok" title="Exact saved evaluation replay">
                    Saved-eval replay
                  </span>
                )}
                {result.demo_mode === "live" && <span className="pill ok">Live RAG</span>}
                <div className="timing">
                  retrieve {result.timings_ms?.retrieve_ms ?? "—"} ms · generate{" "}
                  {result.timings_ms?.generate_ms ?? "—"} ms · total{" "}
                  {result.timings_ms?.total_ms ?? "—"} ms
                </div>
              </div>
            </div>
            <p className="question-echo">{result.question}</p>
            <div className="answer-text">{result.answer}</div>
            <div className="cite-row">
              <span
                className={`cite-pill ${(result.citations?.citation_status || "")
                  .toLowerCase()
                  .replace(/\s+/g, "-")}`}
              >
                Citation: {result.citations?.citation_status || "n/a"}
              </span>
              {result.citations?.cited_source_ids?.length > 0 && (
                <span className="muted">
                  cited {result.citations.cited_source_ids.join(", ")}
                </span>
              )}
            </div>
          </section>

          <section className="xai-grid">
            <div>
              <h2>What happened (explainable view)</h2>
              <p className="muted block-note">
                Each box is one real step in the current system. FAISS searches
                vectors; the LLM only sees English text.
              </p>
              <div className="steps">
                {(result.pipeline_steps || []).map((step, i) => (
                  <StepCard
                    key={step.id}
                    step={step}
                    index={i}
                    active={
                      i === activeStep ||
                      (!loading && i === result.pipeline_steps.length - 1)
                    }
                  />
                ))}
              </div>
              <p className="arch-note">{result.architecture_note}</p>
            </div>

            <div>
              <h2>Retrieved evidence (FAISS Top-{result.retrieval?.top_k || 5})</h2>
              <p className="muted block-note">
                Model: {result.retrieval?.e5_model} · Index:{" "}
                {result.retrieval?.faiss_index} · {result.retrieval?.n_chunks} chunks
              </p>
              <div className="hits">
                {(result.retrieval?.hits || []).map((hit) => (
                  <HitCard
                    key={hit.chunk_id}
                    hit={hit}
                    expanded={!!expandedHits[hit.chunk_id]}
                    onToggle={() =>
                      setExpandedHits((prev) => ({
                        ...prev,
                        [hit.chunk_id]: !prev[hit.chunk_id],
                      }))
                    }
                  />
                ))}
              </div>

              <div className="llm-box">
                <h3>LLM stage</h3>
                <ul>
                  <li>
                    <strong>Runtime:</strong> Ollama (not the model)
                  </li>
                  <li>
                    <strong>Model:</strong> {result.generation?.model}
                  </li>
                  <li>
                    <strong>Context window used:</strong> {result.generation?.num_ctx}
                  </li>
                  <li>
                    <strong>Temperature:</strong> {result.generation?.temperature}
                  </li>
                  <li>
                    <strong>Prompt tokens:</strong>{" "}
                    {result.generation?.prompt_eval_count ?? "—"}
                  </li>
                  <li>
                    <strong>Output tokens:</strong> {result.generation?.eval_count ?? "—"}
                  </li>
                </ul>
                <button
                  type="button"
                  className="ghost-btn"
                  onClick={() => setShowPrompt((v) => !v)}
                >
                  {showPrompt ? "Hide evidence prompt" : "Show evidence sent to LLM"}
                </button>
                {showPrompt && (
                  <pre className="prompt-view">{result.generation?.context_sent_to_llm}</pre>
                )}
              </div>
            </div>
          </section>
        </div>
      )}

      <footer className="foot">
        Frozen baseline: multilingual-e5-large → FAISS IndexFlatIP → Top-5 → Step-14
        prompt → qwen2.5:3b. Sample chips replay saved evaluations instantly; typed
        novel questions attempt live RAG.
      </footer>
    </div>
  );
}
