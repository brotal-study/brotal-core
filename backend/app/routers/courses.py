"""Router de ramos y packs /api/v1/courses (Issue #3)."""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Annotated, Any

import httpx
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import ValidationError

from app.db.database import get_conn
from app.schemas.career import CourseStatus
from app.schemas.pack import CourseOut, CoursePatch, ManualCourseCreate
from app.services.ingest import ingest_local_files
from app.services.pack_manager import (
    archive_course,
    ensure_career_installed,
    export_pack,
    install_pack,
    load_fixture_career,
    load_fixture_pack,
    resolve_course_row,
)

router = APIRouter(tags=["courses"])

DbConn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _row_to_course_out(row: sqlite3.Row) -> CourseOut:
    meta: dict[str, Any] = {}
    if row["pack_metadata_json"]:
        try:
            parsed = json.loads(row["pack_metadata_json"])
            if isinstance(parsed, dict):
                meta = parsed
        except json.JSONDecodeError:
            meta = {}
    code = row["course_code"] or row["id"]
    return CourseOut(
        id=row["id"],
        career_id=row["career_id"],
        course_code=row["course_code"],
        code=code,
        title=row["title"],
        name=row["title"],
        credits=int(meta.get("credits", 0)),
        category=str(meta.get("category", "inf")),
        engine_type=row["engine_type"],
        status=row["status"],
        source_type=row["source_type"],
        pack_version=row["pack_version"],
        created_year=row["created_year"],
        updated_year=row["updated_year"],
        manual=bool(meta.get("manual", False)),
        updated_at=row["updated_at"],
    )


def _ensure_course_from_career(conn: sqlite3.Connection, course_code: str) -> sqlite3.Row | None:
    row = resolve_course_row(conn, course_code)
    if row is not None:
        return row

    prof = conn.execute("SELECT career_id FROM user_profile WHERE id = 1;").fetchone()
    career_id = prof["career_id"] if prof and prof["career_id"] else load_fixture_career().id
    manifest = ensure_career_installed(conn, career_id)
    if manifest is None:
        manifest = load_fixture_career()

    for sem in manifest.semesters:
        for c in sem.courses:
            if c.code == course_code:
                meta = json.dumps({"credits": c.credits, "category": c.category, "semester": sem.number})
                conn.execute(
                    """
                    INSERT INTO courses (
                        id, career_id, course_code, title, engine_type, status, source_type, pack_metadata_json
                    )
                    VALUES (?, ?, ?, ?, 'concept_tree', 'pending', 'local', ?);
                    """,
                    (c.code, manifest.id, c.code, c.name, meta),
                )
                conn.commit()
                return resolve_course_row(conn, c.code)
    return None


@router.get("/courses", response_model=list[CourseOut])
def list_courses(
    conn: DbConn,
    status: Annotated[CourseStatus | None, Query()] = None,
) -> list[CourseOut]:
    if status is not None:
        rows = conn.execute(
            "SELECT * FROM courses WHERE status = ? ORDER BY updated_at DESC, id ASC;",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM courses ORDER BY updated_at DESC, id ASC;").fetchall()
    return [_row_to_course_out(r) for r in rows]


@router.post("/courses/manual", response_model=CourseOut, status_code=201)
def create_manual_course(
    body: ManualCourseCreate,
    conn: DbConn,
) -> CourseOut:
    course_id = (body.id.strip() if body.id else "") or f"manual-{uuid.uuid4().hex[:8]}"
    code = body.code.strip() or "LIBRE"
    name = body.name.strip()
    meta = json.dumps(
        {"manual": True, "credits": body.credits, "category": body.category},
        ensure_ascii=False,
    )
    conn.execute(
        """
        INSERT INTO courses (
            id, career_id, course_code, title, engine_type, status, source_type, pack_metadata_json
        )
        VALUES (?, NULL, ?, ?, 'concept_tree', 'pending', 'local', ?);
        """,
        (course_id, code, name, meta),
    )
    conn.commit()
    row = resolve_course_row(conn, course_id)
    assert row is not None
    return _row_to_course_out(row)


@router.post("/courses/install-pack")
def post_install_pack(
    payload: Annotated[dict[str, Any], Body()],
    conn: DbConn,
) -> dict[str, Any]:
    pack_dict: dict[str, Any] | None = None

    if "schema_version" in payload or "nodes" in payload or "course_code" in payload:
        pack_dict = payload
    elif isinstance(payload.get("pack"), dict):
        pack_dict = payload["pack"]
    elif isinstance(payload.get("pack_id"), str):
        pack_id = payload["pack_id"]
        demo = load_fixture_pack()
        if pack_id in (demo.id, demo.course_code):
            pack_dict = demo.model_dump()
        else:
            raise HTTPException(status_code=404, detail=f"Pack '{pack_id}' not found")
    elif isinstance(payload.get("url") or payload.get("pack_url"), str):
        url = str(payload.get("url") or payload.get("pack_url"))
        demo = load_fixture_pack()
        if demo.id in url or url.startswith("fixtures/"):
            pack_dict = demo.model_dump()
        else:
            try:
                resp = httpx.get(url, timeout=10.0)
                resp.raise_for_status()
                pack_dict = resp.json()
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Could not fetch pack URL: {exc}") from exc
    else:
        pack_dict = payload

    try:
        course_id = install_pack(conn, pack_dict)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    row = resolve_course_row(conn, course_id)
    assert row is not None
    return {
        "course_id": row["id"],
        "id": row["id"],
        "pack_id": row["id"],
        "course_code": row["course_code"],
        "title": row["title"],
        "status": row["status"],
        "version": row["pack_version"],
    }


@router.post("/courses/ingest-local")
async def post_ingest_local(
    conn: DbConn,
    course_code: Annotated[str, Form()],
    title: Annotated[str, Form()],
    files: Annotated[list[UploadFile], File()],
    career_id: Annotated[str | None, Form()] = None,
    world_metaphor: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="Debes adjuntar al menos un archivo.")

    conn.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1);")
    prof = conn.execute("SELECT ai_provider, career_id FROM user_profile WHERE id = 1;").fetchone()
    ai_provider = prof["ai_provider"] if prof else "auto"
    effective_career_id = career_id if career_id is not None else (prof["career_id"] if prof else None)

    file_tuples: list[tuple[str, bytes]] = []
    for up in files:
        raw = await up.read()
        file_tuples.append((up.filename or "apunte.txt", raw))

    try:
        return ingest_local_files(
            conn,
            course_code=course_code,
            title=title,
            career_id=effective_career_id,
            world_metaphor=world_metaphor,
            files=file_tuples,
            preferred_provider=ai_provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/courses/{course_id}", response_model=CourseOut)
def patch_course(
    course_id: str,
    patch: CoursePatch,
    conn: DbConn,
) -> CourseOut:
    row = _ensure_course_from_career(conn, course_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    real_id = row["id"]
    if patch.status == "archived":
        archive_course(conn, real_id)
    elif patch.status is not None:
        conn.execute(
            "UPDATE courses SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (patch.status, real_id),
        )
        conn.commit()

    if patch.title is not None:
        conn.execute(
            "UPDATE courses SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (patch.title.strip(), real_id),
        )
        conn.commit()

    updated = resolve_course_row(conn, real_id)
    assert updated is not None
    return _row_to_course_out(updated)


@router.delete("/courses/{course_id}")
def delete_course(
    course_id: str,
    conn: DbConn,
) -> dict[str, str]:
    row = resolve_course_row(conn, course_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")
    conn.execute("DELETE FROM courses WHERE id = ?;", (row["id"],))
    conn.commit()
    return {"deleted": row["id"]}


@router.get("/courses/{course_id}/export")
def get_export_pack(
    course_id: str,
    conn: DbConn,
) -> dict[str, Any]:
    try:
        return export_pack(conn, course_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
