"""Private Supabase Storage REST client. Source PDF paths are server-generated."""
from urllib.parse import quote

import httpx

from .config import Settings


class StorageError(RuntimeError):
    pass


class PrivateStorage:
    def __init__(self, cfg: Settings):
        self.cfg = cfg

    def _url(self, path: str, *, authenticated: bool = False) -> str:
        prefix = "/storage/v1/object/authenticated/" if authenticated else "/storage/v1/object/"
        return (self.cfg.supabase_url.rstrip("/") + prefix
                + quote(self.cfg.supabase_storage_bucket, safe="") + "/" + quote(path, safe="/"))

    def _headers(self):
        key = self.cfg.supabase_service_role_key
        return {"Authorization": f"Bearer {key}", "apikey": key}

    def upload(self, path: str, data: bytes):
        try:
            response = httpx.post(self._url(path), headers={**self._headers(), "content-type": "application/pdf", "x-upsert": "false"}, content=data, timeout=60)
        except httpx.HTTPError as exc:
            raise StorageError("PDF storage is unavailable") from exc
        if response.status_code not in (200, 201):
            raise StorageError("PDF storage rejected the upload")

    def download(self, path: str) -> bytes:
        try:
            response = httpx.get(self._url(path, authenticated=True), headers=self._headers(), timeout=60)
        except httpx.HTTPError as exc:
            raise StorageError("PDF storage is unavailable") from exc
        if response.status_code != 200:
            raise StorageError("PDF is unavailable")
        return response.content

    def delete(self, path: str):
        # Supabase object API DELETE supports a single object path.
        try:
            response = httpx.delete(self._url(path), headers=self._headers(), timeout=30)
        except httpx.HTTPError as exc:
            raise StorageError("PDF storage is unavailable") from exc
        if response.status_code not in (200, 204, 404):
            raise StorageError("PDF storage could not delete the object")
