"""Supabase Auth validates the browser's token; the browser never chooses owner_id."""
from uuid import UUID

import httpx
from fastapi import Header, HTTPException

from .config import settings


def verify_access_token(authorization: str | None = Header(default=None)) -> UUID:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in to continue")
    token = authorization[7:].strip()
    if not token or len(token) > 8192:
        raise HTTPException(status_code=401, detail="Invalid session")
    cfg = settings()
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    try:
        response = httpx.get(
            cfg.supabase_url.rstrip("/") + "/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": cfg.supabase_service_role_key},
            timeout=8,
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Authentication is temporarily unavailable") from None
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    try:
        return UUID(response.json()["id"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid session") from None
