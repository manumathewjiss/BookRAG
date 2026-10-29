"""Interactively obtain two test-user sessions without echoing passwords or tokens.

Run from cloud_backend in a local terminal. No model providers are contacted.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path
import shlex
import sys
import tempfile

import httpx

from bookrag_cloud.config import settings


SESSION_FILE = Path("verification_sessions.env")


def sign_in(client: httpx.Client, base_url: str, api_key: str, email: str, password: str) -> tuple[str, str]:
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    response = client.post(
        base_url.rstrip("/") + "/auth/v1/token?grant_type=password",
        headers=headers,
        json={"email": email, "password": password},
    )
    if response.status_code != 200:
        raise RuntimeError("Sign-in failed; check this test user's email and password")
    try:
        token = response.json()["access_token"]
        if not isinstance(token, str) or not token or len(token) > 8192:
            raise ValueError
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Supabase did not return a valid access token") from exc
    check = client.get(
        base_url.rstrip("/") + "/auth/v1/user",
        headers={"apikey": api_key, "Authorization": f"Bearer {token}"},
    )
    if check.status_code != 200:
        raise RuntimeError("Supabase did not accept this user's session")
    try:
        user_id = check.json()["id"]
        if not isinstance(user_id, str) or not user_id:
            raise ValueError
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Supabase returned an invalid user identity") from exc
    return token, user_id


def save_sessions(path: Path, token_a: str, token_b: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".verification_sessions-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write("# Short-lived Supabase test sessions. Do not commit or share.\n")
            output.write(f"export BOOKRAG_SMOKE_USER_A_TOKEN={shlex.quote(token_a)}\n")
            output.write(f"export BOOKRAG_SMOKE_USER_B_TOKEN={shlex.quote(token_b)}\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    if not sys.stdin.isatty():
        print("Run this helper in an interactive local terminal.")
        return 1
    cfg = settings()
    if not cfg.supabase_url or not cfg.supabase_service_role_key:
        print("Supabase project settings are incomplete.")
        return 1
    print("Sign in as the two existing Supabase test users. Passwords will be hidden.")
    try:
        with httpx.Client(timeout=12) as client:
            sessions = []
            for label in ("A", "B"):
                email = input(f"Test user {label} email: ").strip()
                password = getpass.getpass(f"Test user {label} password (hidden): ")
                if not email or not password:
                    raise RuntimeError("Both email and password are required")
                sessions.append(sign_in(client, cfg.supabase_url, cfg.supabase_service_role_key,
                                        email, password))
                password = ""
            if sessions[0][1] == sessions[1][1]:
                raise RuntimeError("The two sessions belong to the same user")
        save_sessions(SESSION_FILE, sessions[0][0], sessions[1][0])
    except (RuntimeError, httpx.HTTPError) as exc:
        # Never show provider response bodies, passwords, or tokens.
        print(str(exc) if isinstance(exc, RuntimeError) else "Supabase Auth is unavailable")
        return 1
    print("Both sessions verified for distinct users. Private session file saved (mode 600).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
