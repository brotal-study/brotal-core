"""Instalar, exportar y archivar Course Packs y gestionar mallas (Issue #3).

Contrato:
- install_pack(conn, pack: dict) -> course_id: inserta courses (source_type='pack', status='active'),
  course_nodes y node_progress (mastery_level=0) para cada nodo. Debe ser idempotente.
- archive_course(conn, course_id): status='archived', borra cache pesada (audios TTS, chunks FTS) y
  CONSERVA node_progress y evaluation_attempts.
- export_pack(conn, course_id) -> dict: pack.json limpio; nunca incluye archivos originales ni rutas locales.
- bulk_status(conn, career_id, up_to_semester, status): marca los ramos de S1..N.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from typing import Any

from app.config import fixtures_dir, tts_cache_dir
from app.schemas.career import CareerManifest
from app.schemas.pack import CoursePack, PackMetadata

_PRIVATE_META_KEYS = {"local_path", "file_path", "source_files", "raw_files", "private_notes"}


def load_fixture_career() -> CareerManifest:
    path = fixtures_dir() / "demo_career.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return CareerManifest.model_validate(data)


def load_fixture_pack() -> CoursePack:
    path = fixtures_dir() / "demo_pack.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return CoursePack.model_validate(data)


def ensure_career_installed(conn: sqlite3.Connection, career_id: str) -> CareerManifest | None:
    row = conn.execute(
        "SELECT manifest_json FROM installed_careers WHERE id = ?;",
        (career_id,),
    ).fetchone()
    if row is not None:
        return CareerManifest.model_validate(json.loads(row["manifest_json"]))

    demo = load_fixture_career()
    if demo.id != career_id:
        return None

    conn.execute(
        """
        INSERT OR REPLACE INTO installed_careers (id, manifest_json)
        VALUES (?, ?);
        """,
        (demo.id, json.dumps(demo.model_dump(exclude_none=True), ensure_ascii=False)),
    )
    conn.commit()
    return demo


def resolve_course_row(conn: sqlite3.Connection, course_id_or_code: str) -> sqlite3.Row | None:
    row = conn.execute(
        """
        SELECT * FROM courses
        WHERE id = ? OR course_code = ?
        ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END,
                 CASE WHEN source_type = 'pack' THEN 0 ELSE 1 END
        LIMIT 1;
        """,
        (course_id_or_code, course_id_or_code, course_id_or_code),
    ).fetchone()
    return row


def install_pack(conn: sqlite3.Connection, pack: dict[str, Any]) -> str:
    """Valida e instala un CoursePack de forma idempotente y lo deja en estado 'active'."""
    validated = CoursePack.model_validate(pack)
    course_id = validated.id
    career_id = validated.metadata.career_ids[0] if validated.metadata.career_ids else None

    clean_meta = validated.metadata.model_dump()
    clean_meta["language"] = validated.language

    # Si existia una fila placeholder local solo por codigo (ej. de bulk_status), consolidar en course_id
    placeholder = conn.execute(
        "SELECT id FROM courses WHERE course_code = ? AND id != ? AND source_type = 'local';",
        (validated.course_code, course_id),
    ).fetchone()
    if placeholder is not None:
        conn.execute("DELETE FROM courses WHERE id = ?;", (placeholder["id"],))

    conn.execute(
        """
        INSERT INTO courses (
            id, career_id, course_code, title, engine_type,
            status, source_type, pack_version, created_year, updated_year,
            pack_metadata_json, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'active', 'pack', ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
            career_id = excluded.career_id,
            course_code = excluded.course_code,
            title = excluded.title,
            engine_type = excluded.engine_type,
            status = 'active',
            source_type = 'pack',
            pack_version = excluded.pack_version,
            created_year = excluded.created_year,
            updated_year = excluded.updated_year,
            pack_metadata_json = excluded.pack_metadata_json,
            updated_at = CURRENT_TIMESTAMP;
        """,
        (
            course_id,
            career_id,
            validated.course_code,
            validated.title,
            validated.engine_type,
            validated.metadata.version,
            validated.metadata.created_year,
            validated.metadata.updated_year,
            json.dumps(clean_meta, ensure_ascii=False),
        ),
    )

    for node in validated.nodes:
        conn.execute(
            """
            INSERT INTO course_nodes (
                id, course_id, parent_ids_json, branch, block_label,
                title, summary, story_script, eval_prompts_json, storyboard_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(course_id, id) DO UPDATE SET
                parent_ids_json = excluded.parent_ids_json,
                branch = excluded.branch,
                block_label = excluded.block_label,
                title = excluded.title,
                summary = excluded.summary,
                story_script = excluded.story_script,
                eval_prompts_json = excluded.eval_prompts_json,
                storyboard_json = excluded.storyboard_json;
            """,
            (
                node.id,
                course_id,
                json.dumps(node.parent_ids, ensure_ascii=False),
                node.branch,
                node.block,
                node.title,
                node.summary,
                node.story_script,
                json.dumps([p.model_dump() for p in node.eval_prompts], ensure_ascii=False),
                json.dumps(node.storyboard_ref) if node.storyboard_ref is not None else None,
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO node_progress (
                course_id, node_id, mastery_level, next_review_at,
                training_reps, best_score, last_score, last_practiced_at
            )
            VALUES (?, ?, 0, NULL, 0, 0, NULL, NULL);
            """,
            (course_id, node.id),
        )

    conn.commit()
    return course_id


def archive_course(conn: sqlite3.Connection, course_id: str) -> None:
    """Marca el ramo como 'archived', borra cache TTS y chunks FTS, y conserva node_progress."""
    row = resolve_course_row(conn, course_id)
    if row is None:
        raise KeyError(f"Course '{course_id}' not found")

    real_id = row["id"]
    conn.execute(
        "UPDATE courses SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
        (real_id,),
    )
    conn.execute("DELETE FROM local_chunks_fts WHERE course_id = ?;", (real_id,))
    if row["course_code"]:
        conn.execute("DELETE FROM local_chunks_fts WHERE course_id = ?;", (row["course_code"],))

    cache_root = tts_cache_dir()
    for key in {real_id, course_id, row["course_code"] or ""}:
        if not key:
            continue
        course_cache_dir = cache_root / key
        if course_cache_dir.is_dir():
            shutil.rmtree(course_cache_dir, ignore_errors=True)
        for f in cache_root.glob(f"{key}_*"):
            if f.is_file():
                f.unlink(missing_ok=True)

    conn.commit()


def export_pack(conn: sqlite3.Connection, course_id: str) -> dict[str, Any]:
    """Exporta un pack.json limpio validado contra CoursePack, sin rutas ni archivos privados."""
    row = resolve_course_row(conn, course_id)
    if row is None:
        raise KeyError(f"Course '{course_id}' not found")

    real_id = row["id"]
    node_rows = conn.execute(
        "SELECT * FROM course_nodes WHERE course_id = ? ORDER BY rowid ASC;",
        (real_id,),
    ).fetchall()
    if not node_rows:
        raise ValueError(f"Course '{course_id}' has no nodes to export")

    raw_meta: dict[str, Any] = {}
    if row["pack_metadata_json"]:
        try:
            loaded = json.loads(row["pack_metadata_json"])
            if isinstance(loaded, dict):
                raw_meta = {k: v for k, v in loaded.items() if k not in _PRIVATE_META_KEYS}
        except json.JSONDecodeError:
            raw_meta = {}

    language = str(raw_meta.pop("language", "es"))
    metadata = PackMetadata(
        university_id=str(raw_meta.get("university_id") or "local"),
        career_ids=list(raw_meta.get("career_ids") or ([row["career_id"]] if row["career_id"] else [])),
        created_year=int(row["created_year"] or raw_meta.get("created_year") or 2026),
        updated_year=int(row["updated_year"] or raw_meta.get("updated_year") or 2026),
        version=str(row["pack_version"] or raw_meta.get("version") or "1.0.0"),
        authors=list(raw_meta.get("authors") or ["Estudiante"]),
        license=str(raw_meta.get("license") or "CC-BY-SA-4.0"),
        world_metaphor=raw_meta.get("world_metaphor"),
    )

    nodes: list[dict[str, Any]] = []
    for n in node_rows:
        storyboard_ref = None
        if n["storyboard_json"]:
            try:
                storyboard_ref = json.loads(n["storyboard_json"])
            except json.JSONDecodeError:
                storyboard_ref = None
        nodes.append(
            {
                "id": n["id"],
                "parent_ids": json.loads(n["parent_ids_json"] or "[]"),
                "branch": n["branch"],
                "block": n["block_label"] or "",
                "title": n["title"],
                "summary": n["summary"] or "",
                "story_script": n["story_script"] or "",
                "eval_prompts": json.loads(n["eval_prompts_json"] or "[]"),
                "storyboard_ref": storyboard_ref,
            }
        )

    pack_obj = CoursePack(
        schema_version="1.0",
        id=real_id,
        course_code=row["course_code"] or real_id,
        title=row["title"],
        language=language,
        engine_type=row["engine_type"],
        metadata=metadata,
        nodes=nodes,
    )
    return pack_obj.model_dump()


def bulk_status(
    conn: sqlite3.Connection,
    career_id: str,
    up_to_semester: int,
    status: str = "passed",
) -> int:
    """Marca los ramos no opcionales de S1..up_to_semester con `status` y devuelve cuantos cambiaron."""
    if status not in ("pending", "active", "passed", "archived"):
        raise ValueError(f"Invalid status '{status}'")

    manifest = ensure_career_installed(conn, career_id)
    if manifest is None:
        raise KeyError(f"Career '{career_id}' not found")

    changed = 0
    for sem in manifest.semesters:
        if sem.number > up_to_semester:
            continue
        for course in sem.courses:
            if course.optional:
                continue
            existing = resolve_course_row(conn, course.code)
            if existing is not None:
                if existing["status"] != status:
                    conn.execute(
                        "UPDATE courses SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
                        (status, existing["id"]),
                    )
                    changed += 1
            else:
                if status != "pending":
                    conn.execute(
                        """
                        INSERT INTO courses (
                            id, career_id, course_code, title, engine_type, status, source_type
                        )
                        VALUES (?, ?, ?, ?, 'concept_tree', ?, 'local');
                        """,
                        (course.code, career_id, course.code, course.name, status),
                    )
                    changed += 1

    conn.commit()
    return changed
