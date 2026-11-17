"""Short-lived, authenticated question previews; no extra database table."""
import base64
import hashlib
import hmac
import json
import time
from uuid import UUID


def _key(secret: str) -> bytes:
    return hashlib.sha256(("bookrag-question-preview-v1:" + secret).encode()).digest()


def sign_preview(secret: str, owner: UUID, document_id: UUID, digest: str,
                 question: str, language: str, native: str, english: str) -> str:
    data = {"owner": str(owner), "document": str(document_id), "digest": digest,
            "question": question, "language": language, "native": native,
            "english": english, "expires": int(time.time()) + 600}
    encoded = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()).decode().rstrip("=")
    signature = hmac.new(_key(secret), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + signature


def verify_preview(secret: str, token: str, owner: UUID, document_id: UUID,
                   digest: str, question: str, language: str) -> dict | None:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(_key(secret), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if (data.get("owner") != str(owner) or data.get("document") != str(document_id)
                or data.get("digest") != digest or data.get("question") != question
                or data.get("language") != language or data.get("expires", 0) < time.time()):
            return None
        if (not isinstance(data.get("english"), str) or len(data["english"]) < 8
                or len(data["english"]) > 1200):
            return None
        return data
    except (ValueError, TypeError, KeyError):
        return None
