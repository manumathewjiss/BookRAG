"""Offline checks for the private, interactive Auth preflight helper."""
import os
from pathlib import Path

import pytest

from scripts.prepare_smoke_sessions import save_sessions, sign_in


class Reply:
    def __init__(self, status, data):
        self.status_code = status
        self.data = data

    def json(self):
        return self.data


class FakeClient:
    def __init__(self, token="private-token", user_id="user-a", accepted=True):
        self.token, self.user_id, self.accepted = token, user_id, accepted

    def post(self, url, *, headers, json):
        assert url.endswith("/auth/v1/token?grant_type=password")
        assert json == {"email": "test@example.org", "password": "hidden-password"}
        return Reply(200 if self.accepted else 401, {"access_token": self.token})

    def get(self, url, *, headers):
        assert url.endswith("/auth/v1/user")
        assert headers["Authorization"] == "Bearer " + self.token
        return Reply(200, {"id": self.user_id})


def test_sign_in_verifies_session_without_returning_password():
    assert sign_in(FakeClient(), "https://test.supabase.co", "server-key",
                   "test@example.org", "hidden-password") == ("private-token", "user-a")
    with pytest.raises(RuntimeError, match="Sign-in failed"):
        sign_in(FakeClient(accepted=False), "https://test.supabase.co", "server-key",
                "test@example.org", "hidden-password")


def test_sessions_are_private_and_replace_atomically(tmp_path: Path):
    path = tmp_path / "verification_sessions.env"
    save_sessions(path, "first.token", "second.token")
    assert os.stat(path).st_mode & 0o777 == 0o600
    text = path.read_text()
    assert "BOOKRAG_SMOKE_USER_A_TOKEN=first.token" in text
    assert "BOOKRAG_SMOKE_USER_B_TOKEN=second.token" in text
    save_sessions(path, "new.token", "newer.token")
    assert "first.token" not in path.read_text()
    assert os.stat(path).st_mode & 0o777 == 0o600
