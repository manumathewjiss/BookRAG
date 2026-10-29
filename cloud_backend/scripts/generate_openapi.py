"""Run after an API change, then verify with pytest."""
import json
from pathlib import Path

from bookrag_cloud.main import app

target = Path(__file__).resolve().parents[1] / "API_OPENAPI_v1.json"
target.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(target)
