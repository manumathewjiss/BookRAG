from bookrag_cloud.config import Settings
from bookrag_cloud.storage import PrivateStorage


def test_private_download_uses_authenticated_endpoint(monkeypatch):
    import bookrag_cloud.storage as module
    seen = {}
    class Response:
        status_code = 200
        content = b"%PDF-1.7"
    def fake(url, headers, timeout):
        seen["url"] = url
        return Response()
    monkeypatch.setattr(module.httpx, "get", fake)
    storage = PrivateStorage(Settings(supabase_url="https://example.supabase.co", supabase_service_role_key="test-key"))
    assert storage.download("owner/doc/source.pdf") == b"%PDF-1.7"
    assert "/object/authenticated/bookrag-pdfs/owner/doc/source.pdf" in seen["url"]
