"""Instalar, exportar y archivar Course Packs. STUB - Issue #3.

Contrato:
- install_pack(conn, pack: dict) -> course_id: inserta courses (source_type='pack', status='active'),
  course_nodes y node_progress (mastery_level=0) para cada nodo. Debe ser idempotente.
- archive_course(conn, course_id): status='archived', borra cache pesada (audios TTS, chunks FTS) y
  CONSERVA node_progress y evaluation_attempts.
- export_pack(conn, course_id) -> dict: pack.json limpio; nunca incluye archivos originales ni rutas locales.
- bulk_status(conn, career_id, up_to_semester, status): marca los ramos de S1..N.
"""
import sqlite3


def install_pack(conn: sqlite3.Connection, pack: dict) -> str:
    raise NotImplementedError("Issue #3")


def archive_course(conn: sqlite3.Connection, course_id: str) -> None:
    raise NotImplementedError("Issue #3")


def export_pack(conn: sqlite3.Connection, course_id: str) -> dict:
    raise NotImplementedError("Issue #3")


def bulk_status(conn: sqlite3.Connection, career_id: str, up_to_semester: int, status: str) -> int:
    raise NotImplementedError("Issue #3")
