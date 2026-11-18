"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CitationPanel } from "@/components/CitationPanel";
import { EmptyState } from "@/components/EmptyState";
import { StatusBadge } from "@/components/StatusBadge";
import { PdfViewer } from "@/components/PdfViewer";
import { getClient } from "@/lib/api";
import { isWithheldAnswer, type Citation, type Document, type QuestionPreview } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/AuthProvider";
import { useApiGuard } from "@/lib/auth/useApiGuard";
import { loadHistory, saveHistory, type ChatTurn } from "@/lib/chat/history";
import { displayAnswerText } from "@/lib/chat/display";
import { ANSWER_LANGUAGES, loadAnswerLanguage, saveAnswerLanguage, loadQuestionLanguage, saveQuestionLanguage, type AnswerLanguage } from "@/lib/chat/answer-language";
import { DOCUMENT_POLL_MS, MAX_QUESTION_CHARS, MIN_QUESTION_CHARS } from "@/lib/config";
import { validateQuestion } from "@/lib/pdf/validate";

export function ChatWorkspace({ documentId }: { documentId: string }) {
  const { getAccessToken, session } = useAuth();
  const client = useMemo(() => getClient(getAccessToken), [getAccessToken]);
  const guard = useApiGuard();
  const userId = session?.user.id || "anon";
  const [doc, setDoc] = useState<Document | null>(null);
  const [turns, setTurns] = useState<ChatTurn[] | null>(null);
  const [question, setQuestion] = useState("");
  const [answerLanguage, setAnswerLanguage] = useState<AnswerLanguage>("en");
  const [questionLanguage, setQuestionLanguage] = useState<AnswerLanguage>("en");
  const [preview, setPreview] = useState<QuestionPreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [waitSeconds, setWaitSeconds] = useState(0);
  const [activeCite, setActiveCite] = useState<Citation | null>(null);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [voiceReviewPending, setVoiceReviewPending] = useState(false);
  const [voiceDetectedLanguage, setVoiceDetectedLanguage] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recordTimerRef = useRef<number | null>(null);

  const visibleTurns = turns ?? [];
  const newestFirstTurns = [...visibleTurns].reverse();
  const lastOk = newestFirstTurns.find((t) => t.status === "ok" && t.answer);
  const waitingNotes = [
    "BookRAG first checks whether this question was answered before.",
    "For new questions, BookRAG searches passages in this PDF.",
    doc?.is_sample ? "If support is found, page references and short excerpts will appear." : "If support is found, you can open the cited PDF pages.",
  ];

  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    const timer = window.setInterval(() => setWaitSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  useEffect(() => () => {
    if (recordTimerRef.current !== null) window.clearTimeout(recordTimerRef.current);
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = null;
      recorder.stop();
      recorder.stream.getTracks().forEach((track) => track.stop());
    }
  }, []);

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser cannot record audio. Please type your question instead.");
      return;
    }
    const mimeType = ["audio/webm", "audio/ogg", "audio/mp4"].find((type) => MediaRecorder.isTypeSupported(type));
    if (!mimeType) {
      setError("This browser has no supported recording format. Please type your question instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const recorder = new MediaRecorder(stream, { mimeType });
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        setRecording(false);
        if (recordTimerRef.current !== null) window.clearTimeout(recordTimerRef.current);
        const blob = new Blob(chunks, { type: mimeType });
        if (!blob.size) { setError("No speech was recorded. Please try again."); return; }
        if (blob.size > 1_000_000) { setError("Recording is too large. Try a shorter question."); return; }
        setTranscribing(true);
        const extension = mimeType.split("/")[1];
        void client.transcribeQuestion(documentId, new File([blob], `question.${extension}`, { type: mimeType }), questionLanguage)
          .then((result) => { setQuestion(result.text); setPreview(null); setVoiceDetectedLanguage(result.detected_language); setVoiceReviewPending(true); setError(""); })
          .catch(async (err) => setError(await guard(err)))
          .finally(() => setTranscribing(false));
      };
      recorder.start();
      setError("");
      setRecording(true);
      recordTimerRef.current = window.setTimeout(() => {
        if (recorder.state === "recording") recorder.stop();
      }, 60_000);
    } catch {
      setError("Microphone access was not available. Please allow it or type your question.");
    }
  }

  function stopRecording() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  useEffect(() => {
    setTurns(loadHistory(userId, documentId));
  }, [documentId, userId]);

  useEffect(() => {
    setAnswerLanguage(loadAnswerLanguage(userId));
    setQuestionLanguage(loadQuestionLanguage(userId));
  }, [userId]);

  useEffect(() => {
    if (turns === null) return;
    saveHistory(userId, documentId, turns);
  }, [documentId, turns, userId]);

  const loadDoc = useCallback(async () => {
    const next = await client.getDocument(documentId);
    setDoc(next);
    setError("");
  }, [client, documentId]);

  useEffect(() => {
    void loadDoc().catch(async (err) => setError(await guard(err)));
  }, [guard, loadDoc]);

  useEffect(() => {
    if (!doc || (doc.status !== "queued" && doc.status !== "processing")) return;
    const timer = window.setInterval(() => {
      void loadDoc().catch(async (err) => setError(await guard(err)));
    }, DOCUMENT_POLL_MS);
    return () => window.clearInterval(timer);
  }, [doc, guard, loadDoc]);

  async function ask() {
    if (voiceReviewPending && voiceDetectedLanguage && voiceDetectedLanguage !== questionLanguage) {
      setError(`Your recording sounds like ${ANSWER_LANGUAGES[voiceDetectedLanguage as AnswerLanguage] || "another language"}. Select that question language or record again.`);
      return;
    }
    if (voiceReviewPending) {
      const check = validateQuestion(question, MIN_QUESTION_CHARS, MAX_QUESTION_CHARS);
      if (!check.ok) { setError(check.message); return; }
      setVoiceReviewPending(false);
      setError("");
      return;
    }
    const check = validateQuestion(question, MIN_QUESTION_CHARS, MAX_QUESTION_CHARS);
    if (!check.ok) {
      setError(check.message);
      return;
    }
    if (!doc || doc.status !== "ready") {
      setError("Wait until this PDF is ready before asking.");
      return;
    }
    if (questionLanguage !== "en" && (!preview || preview.original_question !== question.trim()
        || preview.question_language !== questionLanguage || !preview.preview_token)) {
      setBusy(true);
      setPreparing(true);
      setError("");
      try {
        const prepared = await client.prepareQuestion(documentId, question.trim(), questionLanguage);
        setPreview(prepared);
        if (prepared.needs_clarification && !prepared.language_warning) setError("Please clarify or reword your question, then review it again.");
      } catch (err) {
        setError(await guard(err));
      } finally {
        setBusy(false);
        setPreparing(false);
      }
      return;
    }
    const turn: ChatTurn = {
      id: crypto.randomUUID(),
      question: question.trim(),
      answer_language: answerLanguage,
      createdAt: new Date().toISOString(),
      status: "pending",
    };
    setTurns((prev) => [...(prev ?? []), turn]);
    setBusy(true);
    setWaitSeconds(0);
    setError("");
    try {
      const answer = await client.chat(documentId, question.trim(), answerLanguage,
        questionLanguage, preview?.preview_token ?? null);
      setTurns((prev) =>
        (prev ?? []).map((item) => (item.id === turn.id ? { ...item, status: "ok" as const, answer } : item)),
      );
      setActiveCite(answer.citations[0] || null);
      setQuestion("");
      setPreview(null);
    } catch (err) {
      const message = await guard(err);
      setTurns((prev) =>
        (prev ?? []).map((item) =>
          item.id === turn.id ? { ...item, status: "error" as const, error: message } : item,
        ),
      );
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page chat-page">
      <div className="chat-heading">
        <div>
          <p className="eyebrow"><Link href="/library">Library</Link> <span aria-hidden="true">›</span> {doc?.title || "PDF"}</p>
          <h1>Ask your book</h1>
          <p>{doc?.is_sample ? "Get answers with page references and short supporting excerpts." : "Get an answer grounded in the pages of your PDF."}</p>
        </div>
        <Link className="ghost" href="/library">View library</Link>
      </div>
      <div className="chat-document-label">
        <span className="chat-document-icon" aria-hidden="true">▤</span>
        <span><strong>{doc?.title || "Loading PDF…"}</strong><small>{doc?.filename || ""}</small></span>
        {doc ? <StatusBadge status={doc.status} /> : null}
      </div>

      <div className="chat-desk">
        <main className="chat-main">
          <div className="section-heading"><h2>Ask a question</h2><span>One PDF at a time</span></div>
          <div className="question-language-row">
            <label className="answer-language-picker" htmlFor="question-language">
              <span>Question language</span>
              <select id="question-language" value={questionLanguage} disabled={busy || recording || transcribing} onChange={(event) => {
                const next = event.target.value as AnswerLanguage;
                setQuestionLanguage(next);
                saveQuestionLanguage(userId, next);
                setPreview(null);
                setError("");
              }}>
                {Object.entries(ANSWER_LANGUAGES).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
              </select>
            </label>
          <label className="answer-language-picker" htmlFor="answer-language">
            <span>Answer language</span>
            <select id="answer-language" value={answerLanguage} disabled={busy || recording || transcribing} onChange={(event) => {
              const next = event.target.value as AnswerLanguage;
              setAnswerLanguage(next);
              saveAnswerLanguage(userId, next);
            }}>
              {Object.entries(ANSWER_LANGUAGES).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
            </select>
          </label>
          </div>
          <p className="answer-language-note">For another question language, type its words using English letters or its own script. Review the script and English meaning before asking.</p>
          <div className="ask-row">
            <textarea
              value={question}
              maxLength={MAX_QUESTION_CHARS}
              disabled={busy || recording || transcribing || doc?.status !== "ready"}
              placeholder={doc?.status === "ready" ? "What does this PDF say about…?" : "The PDF must finish processing before you can ask"}
              onChange={(e) => { setQuestion(e.target.value); setPreview(null); setVoiceDetectedLanguage(null); setError(""); }}
              onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void ask(); }}
              aria-label="Question"
            />
            <button type="button" onClick={() => void ask()} disabled={busy || recording || transcribing || doc?.status !== "ready" || Boolean(preview?.needs_clarification && preview.original_question === question.trim() && preview.question_language === questionLanguage)} aria-label={voiceReviewPending ? "Confirm transcript" : questionLanguage !== "en" && !preview?.preview_token ? "Review question" : "Ask"}>{voiceReviewPending ? "Confirm text" : questionLanguage !== "en" && !preview?.preview_token ? "Review" : "Ask"} <span aria-hidden="true">→</span></button>
          </div>
          <div className="voice-question-row">
            <button type="button" className={`ghost voice-record-button${recording ? " is-recording" : ""}${transcribing ? " is-transcribing" : ""}`} onClick={recording ? stopRecording : () => void startRecording()}
              disabled={busy || transcribing || doc?.status !== "ready"} aria-label={recording ? "Stop recording" : "Record question"}>
              <span className="voice-record-icon" aria-hidden="true">{recording ? <span className="voice-stop-icon" /> : transcribing ? <span className="voice-spinner" /> : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10a7 7 0 0 0 14 0M12 17v5m-4 0h8" /></svg>}</span>
              {recording ? "Stop recording" : transcribing ? "Transcribing" : "Record question"}
            </button>
            <span role="status">{recording ? "Listening now · up to 60 seconds" : transcribing ? "Turning speech into text…" : voiceReviewPending ? "Check the transcript, then confirm the text." : "Speak your question, then review the text."}</span>
          </div>
          {voiceReviewPending ? <div className="voice-review" role="region" aria-label="Recorded question review">
            <strong>Check your recorded question</strong>
            <p>{voiceDetectedLanguage && voiceDetectedLanguage !== questionLanguage
              ? `This sounds like ${ANSWER_LANGUAGES[voiceDetectedLanguage as AnswerLanguage] || "another language"}, but ${ANSWER_LANGUAGES[questionLanguage]} is selected. Change the question language or record again.`
              : "Edit the text above if anything was heard incorrectly. Press Confirm text to continue. Your question will not be sent yet."}</p>
          </div> : null}
          {preview ? <div className="question-preview" role="region" aria-label="Question review">
            <strong>Check what BookRAG understood</strong>
            {preview.language_warning ? <p className="language-warning">{preview.language_warning}</p> : <>
              <p><span>{ANSWER_LANGUAGES[questionLanguage]} script</span><br />{preview.native_script || "Unclear"}</p>
              <p><span>English meaning used to search the PDF</span><br />{preview.english_meaning || "Unclear"}</p>
            </>}
            {preview.needs_clarification ? !preview.language_warning && <p>Please edit your question and review again.</p>
              : <p>Correct? Press Ask. To change it, edit your original question above.</p>}
          </div> : null}
          {preparing ? <p className="status" role="status">Preparing the script and English meaning for your review…</p> : busy ? (
            <div className="answer-wait" role="status" aria-live="polite">
              <span className="answer-wait-mark" aria-hidden="true" />
              <div className="answer-wait-copy">
                <strong>Finding your answer</strong>
                <span>{waitingNotes[Math.floor(waitSeconds / 5) % waitingNotes.length]}</span>
              </div>
              <span className="answer-wait-time" aria-label={`${waitSeconds} seconds elapsed`} aria-live="off">{waitSeconds}s</span>
            </div>
          ) : question.trim().length > 0 && question.trim().length < MIN_QUESTION_CHARS ? (
            <p className="status">{MIN_QUESTION_CHARS - question.trim().length} more characters needed.</p>
          ) : null}
          {error ? <p className="error-card" role="alert">{error}</p> : null}

          <div className="section-heading answers-heading"><h2>Answers</h2><span>{visibleTurns.length} {visibleTurns.length === 1 ? "question" : "questions"}</span></div>
          <div className="history">
            {visibleTurns.length === 0 ? <EmptyState title="No questions yet">{doc?.is_sample ? "Ask a question about this sample. Page references and short supporting excerpts will appear beside the answer." : "Ask a question that this PDF might answer. The cited page and supporting text will appear beside the answer."}</EmptyState> : null}
            {newestFirstTurns.map((turn) => (
              <article key={turn.id} className="turn-card">
                <p className="turn-question">{turn.question}</p>
                {turn.status === "pending" ? <div className="turn-pending">Answer in progress · Please keep this page open.</div> : null}
                {turn.status === "error" ? <div className="error-card">{turn.error}</div> : null}
                {turn.answer ? (
                  <div className="answer-card">
                    <div className="answer-topline">
                      <span>Pipeline time {((turn.answer.timings_ms.search + turn.answer.timings_ms.rerank + turn.answer.timings_ms.answer) / 1000).toFixed(1)}s</span>
                      <span>{ANSWER_LANGUAGES[turn.answer.answer_language ?? turn.answer_language ?? "en"]}</span>
                      {turn.answer.reused_answer ? <span className="badge idle">Previously answered</span> : null}
                    </div>
                    <p className="answer-text">{isWithheldAnswer(turn.answer) ? "The model claimed support without a valid citation, so this answer is withheld." : displayAnswerText(turn.answer.answer)}</p>
                    <div className="metrics" aria-label="Time breakdown">
                      <div className="metric"><span className="k">Search</span><span>{(turn.answer.timings_ms.search / 1000).toFixed(1)}s</span></div>
                      <div className="metric"><span className="k">Rerank</span><span>{(turn.answer.timings_ms.rerank / 1000).toFixed(1)}s</span></div>
                      <div className="metric"><span className="k">Answer</span><span>{(turn.answer.timings_ms.answer / 1000).toFixed(1)}s</span></div>
                    </div>
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </main>

        <aside className="evidence-panel">
          <div className="section-heading"><h2>Evidence</h2><span>{doc?.is_sample ? "Page references" : "From your PDF"}</span></div>
          <CitationPanel answer={lastOk?.answer || null} question={lastOk?.question || ""} filename={doc?.filename || "document.pdf"} sampleMode={doc?.is_sample} selected={activeCite} onSelect={setActiveCite} />
          {doc?.is_sample ? <p className="empty evidence-empty">The shared sample shows page references and short excerpts. PDF pages are available for your own uploads.</p> : activeCite ? <div className="pdf-panel"><PdfViewer documentId={documentId} filename={doc?.filename || "document.pdf"} page={activeCite.pdf_page} client={client} /></div> : <p className="empty evidence-empty">Select a citation to view the original PDF page.</p>}
        </aside>
      </div>
    </div>
  );
}
