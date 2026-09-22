"""
Lightweight demo HTTP server (stdlib only).

- Sample / saved evaluation questions: instant explainable replay
- Other questions: live E5 + FAISS + Qwen via ask_worker.py (project venv)
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DEMO_ROOT = Path(__file__).resolve().parents[1]
GITA_ROOT = DEMO_ROOT.parent
REPO_ROOT = GITA_ROOT.parent
WORKER = Path(__file__).resolve().parent / "ask_worker.py"
REPLAY_PATH = DEMO_ROOT / "sample_replay.json"

HOST = "127.0.0.1"
PORT = 8000

_REPLAY = None


def load_replay() -> dict:
    global _REPLAY
    if _REPLAY is None:
        if REPLAY_PATH.exists():
            _REPLAY = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
        else:
            _REPLAY = {"by_question": {}, "questions": []}
    return _REPLAY


def worker_python() -> str:
    import os

    # Prefer a venv outside iCloud/Documents — the project ./venv is often
    # APFS-dataless and hangs on import torch.
    candidates = [
        os.environ.get("GITA_VENV_PYTHON"),
        str(Path.home() / ".venvs" / "pramod-gita-rag" / "bin" / "python"),
        str(REPO_ROOT / "venv" / "bin" / "python"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return sys.executable


def run_worker(payload: dict, timeout: int = 600) -> dict:
    import os

    env = {
        **os.environ,
        "PYTHONPATH": str(GITA_ROOT),
        "PYTHONUNBUFFERED": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "KMP_DUPLICATE_LIB_OK": "TRUE",
        "OMP_NUM_THREADS": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    try:
        proc = subprocess.run(
            [worker_python(), str(WORKER)],
            input=json.dumps(payload).encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            env=env,
            cwd=str(DEMO_ROOT),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Live RAG timed out while starting the Python worker. "
            "For the professor demo, click a sample question chip (instant saved-eval replay). "
            "If you need live answers, restart any hung venv Python processes and try again."
        ) from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[-2000:]
        try:
            err = json.loads(proc.stdout.decode("utf-8"))
            detail = err.get("detail") or detail
        except Exception:
            pass
        raise RuntimeError(detail or f"Worker failed with code {proc.returncode}")
    return json.loads(proc.stdout.decode("utf-8"))


def normalize_question(text: str) -> str:
    t = (text or "").strip().lower()
    # Unify curly/smart quotes and dashes so typed questions still hit replay.
    for a, b in (
        ("\u2018", "'"),
        ("\u2019", "'"),
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u2013", "-"),
        ("\u2014", "-"),
    ):
        t = t.replace(a, b)
    return " ".join(t.split())


def lookup_replay(question: str) -> dict | None:
    replay = load_replay().get("by_question", {})
    key = normalize_question(question)
    if key in replay:
        return replay[key]
    # Also try raw lower key for older replay files.
    raw = question.strip().lower()
    return replay.get(raw)

def ollama_reachable() -> bool:
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def local_health() -> dict:
    replay = load_replay()
    # Prefer human-readable sample questions from replay keys (original casing from values)
    samples = []
    for packed in list(replay.get("by_question", {}).values())[:8]:
        samples.append(packed["question"])
    if not samples:
        samples = [
            "What does Bhagavad Gita 2.47 say?",
            "In what way can a person’s own mind be their friend, and in what way can it be their enemy?",
        ]
    return {
        "status": "ok",
        "pipeline": "plain_e5 + faiss IndexFlatIP + qwen2.5:3b (Ollama)",
        "e5_model": "intfloat/multilingual-e5-large",
        "embedding_dim": 1024,
        "n_chunks": 1443,
        "top_k_default": 5,
        "generator": "qwen2.5:3b",
        "num_ctx": 8192,
        "temperature": 0,
        "artifacts": {
            "faiss_index": (GITA_ROOT / "gita_e5.faiss").exists(),
            "metadata": (GITA_ROOT / "gita_e5_metadata.json").exists(),
            "prompt": (GITA_ROOT / "gita_rag_prompt.txt").exists(),
            "sample_replay": REPLAY_PATH.exists(),
        },
        "ollama_reachable": ollama_reachable(),
        "retriever_loaded": False,
        "sample_questions": samples,
        "worker_python": worker_python(),
        "replay_count": len(replay.get("by_question", {})),
        "note": "Sample chips use saved evaluation replays (instant). Other questions try live RAG via the venv worker.",
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/api", "/api/"):
            self._json(
                200,
                {"message": "Gita RAG Demo API", "health": "/api/health", "ask": "POST /api/ask"},
            )
            return
        if path == "/api/health":
            self._json(200, local_health())
            return
        self._json(404, {"detail": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"detail": "Invalid JSON"})
            return

        try:
            if path == "/api/warmup":
                self._json(200, run_worker({"action": "warmup"}, timeout=300))
                return

            if path == "/api/ask":
                question = str(data.get("question") or "").strip()
                top_k = int(data.get("top_k") or 5)
                force_live = bool(data.get("force_live"))
                if len(question) < 3:
                    self._json(400, {"detail": "Question is empty."})
                    return

                if not force_live:
                    replay = lookup_replay(question)
                    if replay is not None:
                        payload = dict(replay)
                        payload["demo_mode"] = "replay_saved_eval"
                        self._json(200, payload)
                        return

                # Live path: first E5 load can take 1–3 minutes on this machine.
                live = run_worker(
                    {"action": "ask", "question": question, "top_k": top_k},
                    timeout=240,
                )
                live["demo_mode"] = "live"
                self._json(200, live)
                return

            self._json(404, {"detail": "Not found"})
        except Exception as exc:
            self._json(503, {"detail": str(exc)})

    def log_message(self, fmt: str, *args):
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))
        sys.stdout.flush()


def main():
    load_replay()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Gita RAG demo API on http://{HOST}:{PORT}", flush=True)
    print(f"Replay questions: {len(load_replay().get('by_question', {}))}", flush=True)
    print(f"Worker Python: {worker_python()}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
