import sqlite3
from pathlib import Path

EXPECTED = {
    "user_profile", "installed_careers", "courses", "course_nodes",
    "node_progress", "evaluation_attempts", "chat_messages", "local_chunks_fts",
}


def test_schema_creates_8_tables():
    conn = sqlite3.connect(":memory:")
    conn.executescript((Path(__file__).parents[1] / "app/db/schema.sql").read_text())
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED <= names
