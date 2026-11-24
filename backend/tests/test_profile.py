from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import db_path
from app.db.database import init_db


def test_init_db_is_idempotent_and_creates_8_tables(isolated_brotal_home: Path) -> None:
    init_db()
    init_db()
    assert db_path().parent == isolated_brotal_home
    assert db_path().is_file()

    conn = sqlite3.connect(str(db_path()))
    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }
        expected = {
            "user_profile",
            "installed_careers",
            "courses",
            "course_nodes",
            "node_progress",
            "evaluation_attempts",
            "chat_messages",
            "local_chunks_fts",
        }
        assert expected <= tables
        count = conn.execute("SELECT COUNT(*) FROM user_profile;").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_get_profile_defaults_and_never_exposes_keys(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_key = "gsk_super_secret_do_not_leak_12345"
    monkeypatch.setenv("GROQ_API_KEY", secret_key)

    res = client.get("/api/v1/profile")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == 1
    assert body["display_name"] == "Estudiante"
    assert body["career_id"] is None
    assert body["curriculum_mode"] == "realistic"
    assert body["cooldown_mode"] == "semester"
    assert body["theme"] == "dark"
    assert body["ai_provider"] == "auto"
    assert body["providers"] == {"groq": True, "gemini": False, "ollama": False}
    assert secret_key not in res.text


def test_patch_profile_persists_across_reinit(client: TestClient) -> None:
    res = client.patch(
        "/api/v1/profile",
        json={
            "display_name": "Yastin",
            "career_id": "cl-pucv-inf-2022",
            "curriculum_mode": "free",
            "cooldown_mode": "urgency",
            "theme": "light",
            "ai_provider": "groq",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["display_name"] == "Yastin"
    assert data["career_id"] == "cl-pucv-inf-2022"
    assert data["curriculum_mode"] == "free"
    assert data["cooldown_mode"] == "urgency"
    assert data["theme"] == "light"
    assert data["ai_provider"] == "groq"

    # Re-run init_db() to simulate server restart
    init_db()
    again = client.get("/api/v1/profile").json()
    assert again["display_name"] == "Yastin"
    assert again["career_id"] == "cl-pucv-inf-2022"

    # Clear career_id (Modo Libre / autodidact)
    cleared = client.patch("/api/v1/profile", json={"career_id": None})
    assert cleared.status_code == 200
    assert cleared.json()["career_id"] is None


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {"curriculum_mode": "invalid_mode"},
        {"cooldown_mode": "daily"},
        {"theme": "blue"},
        {"ai_provider": "openai"},
        {"display_name": ""},
        {"unknown_field": "x"},
    ],
)
def test_patch_profile_rejects_invalid_values(
    client: TestClient,
    invalid_payload: dict[str, str],
) -> None:
    res = client.patch("/api/v1/profile", json=invalid_payload)
    assert res.status_code == 422
