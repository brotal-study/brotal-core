"""Conexion SQLite e inicializacion de tablas. STUB - Issue #2.

Contrato:
- init_db() ejecuta app/db/schema.sql (idempotente, IF NOT EXISTS) y crea la fila id=1 de user_profile.
- get_conn() entrega una conexion con PRAGMA foreign_keys=ON y row_factory=sqlite3.Row
  (usable como dependencia de FastAPI).
"""
import sqlite3
from collections.abc import Iterator
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def init_db() -> None:
    raise NotImplementedError("Issue #2")


def get_conn() -> Iterator[sqlite3.Connection]:
    raise NotImplementedError("Issue #2")
