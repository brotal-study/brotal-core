"""Router de registry comunitario y mallas /api/v1/registry y /api/v1/careers (Issue #3)."""
from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.db.database import get_conn
from app.schemas.career import (
    BulkStatusRequest,
    BulkStatusResponse,
    CareerCourse,
    CareerDetailResponse,
    CareerSummary,
    CourseProgressSummary,
    CourseStatus,
    Semester,
)
from app.services.pack_manager import (
    bulk_status,
    ensure_career_installed,
    load_fixture_career,
)

router = APIRouter(tags=["registry"])

DbConn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _build_registry_payload() -> dict[str, Any]:
    career = load_fixture_career()
    career_summary = CareerSummary(
        id=career.id,
        country=career.country,
        university=career.university.name,
        university_short=career.university.short_name,
        career_name=career.career.name,
        name=career.career.name,
        plan_year=career.career.plan_year,
        plan_ref=career.career.plan_ref,
        manifest_url=f"fixtures/{career.id}.json",
    )
    # Sin packs demo precargados: cada estudiante crea desde sus archivos o instala packs comunitarios reales.
    return {
        "schema_version": "1.0",
        "updated_at": career.career.updated_at,
        "careers": [career_summary.model_dump()],
        "packs": [],
    }


@router.get("/registry")
def get_registry() -> dict[str, Any]:
    return _build_registry_payload()


@router.get("/careers/{career_id}", response_model=CareerDetailResponse)
def get_career_detail(
    career_id: str,
    conn: DbConn,
) -> CareerDetailResponse:
    manifest = ensure_career_installed(conn, career_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Career '{career_id}' not found")

    rows = conn.execute(
        "SELECT id, course_code, status, source_type, pack_version FROM courses WHERE career_id = ? OR course_code IS NOT NULL;",
        (career_id,),
    ).fetchall()

    status_by_code: dict[str, CourseStatus] = {}
    installed_packs: dict[str, str] = {}
    for r in rows:
        code = r["course_code"] or r["id"]
        # Si hay un pack instalado para el mismo codigo, priorizar esa fila
        if code not in status_by_code or r["source_type"] == "pack" or r["pack_version"]:
            status_by_code[code] = r["status"]
        if r["pack_version"]:
            installed_packs[code] = r["pack_version"]

    prog_rows = conn.execute(
        """
        SELECT
            c.id AS course_id,
            c.course_code AS course_code,
            COUNT(cn.id) AS total,
            SUM(CASE WHEN COALESCE(np.mastery_level, 0) >= 3 THEN 1 ELSE 0 END) AS mastered,
            SUM(
                CASE
                    WHEN COALESCE(np.mastery_level, 0) > 0
                      OR COALESCE(np.training_reps, 0) > 0
                      OR COALESCE(np.best_score, 0) > 0
                      OR np.last_practiced_at IS NOT NULL
                    THEN 1 ELSE 0
                END
            ) AS started
        FROM courses c
        INNER JOIN course_nodes cn ON cn.course_id = c.id
        LEFT JOIN node_progress np ON np.course_id = c.id AND np.node_id = cn.id
        WHERE c.career_id = ? OR c.course_code IS NOT NULL
        GROUP BY c.id;
        """,
        (career_id,),
    ).fetchall()

    course_progress: dict[str, CourseProgressSummary] = {}
    for pr in prog_rows:
        code = str(pr["course_code"] or pr["course_id"])
        total = int(pr["total"] or 0)
        mastered = int(pr["mastered"] or 0)
        started = int(pr["started"] or 0)
        existing = course_progress.get(code)
        if existing is None or (total, mastered, started) > (existing.total, existing.mastered, existing.started):
            course_progress[code] = CourseProgressSummary(
                mastered=mastered,
                total=total,
                started=started,
            )

    statuses: dict[str, CourseStatus] = {}
    semesters_out: list[Semester] = []
    credits_total = 0
    credits_passed = 0
    courses_total = 0
    courses_passed = 0

    for sem in manifest.semesters:
        courses_out: list[CareerCourse] = []
        for c in sem.courses:
            st: CourseStatus = status_by_code.get(c.code, "pending")
            statuses[c.code] = st
            courses_out.append(c.model_copy(update={"status": st}))
            if not c.optional:
                courses_total += 1
                credits_total += c.credits
                if st == "passed":
                    courses_passed += 1
                    credits_passed += c.credits
        semesters_out.append(Semester(number=sem.number, label=sem.label, courses=courses_out))

    return CareerDetailResponse(
        schema_version=manifest.schema_version,
        id=manifest.id,
        country=manifest.country,
        university=manifest.university,
        career=manifest.career,
        categories=manifest.categories,
        semesters=semesters_out,
        statuses=statuses,
        installed_packs=installed_packs,
        course_progress=course_progress,
        credits_total=credits_total,
        credits_passed=credits_passed,
        credits_approved=credits_passed,
        courses_total=courses_total,
        courses_passed=courses_passed,
    )


@router.post("/careers/{career_id}/bulk-status", response_model=BulkStatusResponse)
def post_career_bulk_status(
    career_id: str,
    body: BulkStatusRequest,
    conn: DbConn,
) -> BulkStatusResponse:
    try:
        changed = bulk_status(conn, career_id, body.up_to_semester, body.status)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return BulkStatusResponse(
        career_id=career_id,
        up_to_semester=body.up_to_semester,
        status=body.status,
        updated_count=changed,
        changed=changed,
    )
