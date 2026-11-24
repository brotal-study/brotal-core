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
    assert body["explanation_style"] == "narrative"
    assert body["question_style"] == "direct"
    assert body["providers"] == {"groq": True, "gemini": False, "ollama": False}
    assert secret_key not in res.text


def test_idempotent_migration_adds_style_columns_to_existing_db(isolated_brotal_home: Path) -> None:
    # Crear una tabla user_profile antigua (v1.0.2) sin explanation_style ni question_style
    db_file = db_path()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute("DROP TABLE IF EXISTS user_profile;")
        conn.execute(
            """
            CREATE TABLE user_profile (
              id              INTEGER PRIMARY KEY CHECK (id = 1),
              display_name    TEXT NOT NULL DEFAULT 'Estudiante',
              career_id       TEXT,
              curriculum_mode TEXT NOT NULL DEFAULT 'realistic',
              cooldown_mode   TEXT NOT NULL DEFAULT 'semester',
              theme           TEXT NOT NULL DEFAULT 'dark',
              ai_provider     TEXT NOT NULL DEFAULT 'auto',
              created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute("INSERT INTO user_profile (id, display_name) VALUES (1, 'Veterano');")
        conn.commit()
    finally:
        conn.close()

    # Ejecutar init_db() dos veces para verificar migracion idempotente
    init_db()
    init_db()

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    try:
        cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(user_profile);").fetchall()}
        assert "explanation_style" in cols
        assert "question_style" in cols
        row = conn.execute("SELECT * FROM user_profile WHERE id = 1;").fetchone()
        assert row["display_name"] == "Veterano"
        assert row["explanation_style"] == "narrative"
        assert row["question_style"] == "direct"
    finally:
        conn.close()


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
            "explanation_style": "structured",
            "question_style": "scenario",
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
    assert data["explanation_style"] == "structured"
    assert data["question_style"] == "scenario"

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
        {"explanation_style": "poetic"},
        {"question_style": "multiple_choice"},
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
