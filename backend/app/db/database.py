"""Conexion SQLite e inicializacion de tablas (Issue #2).

Contrato:
- init_db() ejecuta app/db/schema.sql (idempotente, IF NOT EXISTS) y crea la fila id=1 de user_profile.
- get_conn() entrega una conexion con PRAGMA foreign_keys=ON y row_factory=sqlite3.Row
  (usable como dependencia de FastAPI).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from app.config import db_path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _migrate_user_profile(conn: sqlite3.Connection) -> None:
    """Agrega columnas nuevas a user_profile de forma idempotente en bases existentes."""
    cols = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(user_profile);").fetchall()
    }
    if "explanation_style" not in cols:
        conn.execute(
            "ALTER TABLE user_profile ADD COLUMN explanation_style TEXT NOT NULL DEFAULT 'narrative' "
            "CHECK (explanation_style IN ('narrative', 'direct', 'structured'));"
        )
    if "question_style" not in cols:
        conn.execute(
            "ALTER TABLE user_profile ADD COLUMN question_style TEXT NOT NULL DEFAULT 'direct' "
            "CHECK (question_style IN ('direct', 'scenario'));"
        )


def init_db() -> None:
    conn = _connect()
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys = ON;")
        _migrate_user_profile(conn)
        conn.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1);")
        conn.commit()
    finally:
        conn.close()


def get_conn() -> Iterator[sqlite3.Connection]:
    init_db()
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
