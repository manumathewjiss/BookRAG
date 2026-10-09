"""
Load local BookRAG secrets from a gitignored .env file.

Never print, log, or return secret values.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
ENV_CANDIDATES = (ROOT / ".env", REPO_ROOT / ".env")


def load_local_env() -> str | None:
    """Load the first existing .env. Existing process env wins (override=False)."""
    for path in ENV_CANDIDATES:
        if path.is_file():
            load_dotenv(path, override=False)
            try:
                return str(path.relative_to(REPO_ROOT))
            except ValueError:
                return path.name
    return None


def openai_api_key_configured() -> bool:
    key = os.environ.get("OPENAI_API_KEY")
    return bool(key and key.strip())
