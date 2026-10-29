import json
from pathlib import Path

from bookrag_cloud.main import app

ROOT = Path(__file__).resolve().parents[1]


def test_static_openapi_matches_running_api():
    saved = json.loads((ROOT / "API_OPENAPI_v1.json").read_text(encoding="utf-8"))
    assert saved == app.openapi()


def test_written_contract_lists_every_public_route():
    contract = (ROOT / "API_CONTRACT_v1.md").read_text(encoding="utf-8")
    for path, methods in app.openapi()["paths"].items():
        for method in methods:
            assert f"`{method.upper()} {path}`" in contract
