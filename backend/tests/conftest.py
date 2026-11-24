from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.database import init_db
from app.main import app


@pytest.fixture(autouse=True)
def isolated_brotal_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "brotal_home"
    monkeypatch.setenv("BROTAL_HOME", str(home))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    init_db()
    return home


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c
