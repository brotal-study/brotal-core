"""Router de estudio y evaluacion /api/v1/courses/{course_id}/tree y /api/v1/study (Issue #4)."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.db.database import get_conn
from app.schemas.pack import PackNode
from app.schemas.study import (
    CourseTreeResponse,
    EvaluateRequest,
    EvaluateResponse,
    NodeProgress,
    PointFeedback,
    normalize_answers,
)
from app.services.evaluator import (
    PASS_SCORE,
    apply_evaluation,
    evaluate_rubric,
    score_from_feedback,
)
from app.services.pack_manager import resolve_course_row

router = APIRouter(tags=["study"])

DbConn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    cleaned = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _format_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


@router.get("/courses/{course_id}/tree", response_model=CourseTreeResponse)
def get_course_tree(
    course_id: str,
    conn: DbConn,
) -> CourseTreeResponse:
    course_row = resolve_course_row(conn, course_id)
    if course_row is None:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    real_id = course_row["id"]
    node_rows = conn.execute(
        "SELECT * FROM course_nodes WHERE course_id = ? ORDER BY rowid ASC;",
        (real_id,),
    ).fetchall()
    if not node_rows:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' has no skill tree installed")

    prog_rows = conn.execute(
        "SELECT * FROM node_progress WHERE course_id = ?;",
        (real_id,),
    ).fetchall()
    prog_by_id = {r["node_id"]: r for r in prog_rows}

    world_metaphor: str | None = None
    if course_row["pack_metadata_json"]:
        try:
            meta = json.loads(course_row["pack_metadata_json"])
            if isinstance(meta, dict):
                world_metaphor = meta.get("world_metaphor")
        except json.JSONDecodeError:
            world_metaphor = None

    nodes: list[PackNode] = []
    progress: dict[str, NodeProgress] = {}

    for r in node_rows:
        nid = r["id"]
        storyboard_ref = None
        if r["storyboard_json"]:
            try:
                storyboard_ref = json.loads(r["storyboard_json"])
            except json.JSONDecodeError:
                storyboard_ref = None

        nodes.append(
            PackNode(
                id=nid,
                parent_ids=json.loads(r["parent_ids_json"] or "[]"),
                branch=r["branch"],
                block=r["block_label"] or "",
                title=r["title"],
                summary=r["summary"] or "",
                story_script=r["story_script"] or "",
                eval_prompts=json.loads(r["eval_prompts_json"] or "[]"),
                storyboard_ref=storyboard_ref,
            )
        )

        pr = prog_by_id.get(nid)
        if pr is not None:
            progress[nid] = NodeProgress(
                node_id=nid,
                mastery_level=pr["mastery_level"],
                next_review_at=pr["next_review_at"],
                training_reps=pr["training_reps"],
                best_score=pr["best_score"],
                last_score=pr["last_score"],
                last_practiced_at=pr["last_practiced_at"],
            )
        else:
            progress[nid] = NodeProgress(node_id=nid)

    return CourseTreeResponse(
        course_id=real_id,
        course_code=course_row["course_code"] or real_id,
        title=course_row["title"],
        world_metaphor=world_metaphor,
        nodes=nodes,
        progress=progress,
    )


@router.post("/study/{course_id}/{node_id}/evaluate", response_model=EvaluateResponse)
def post_evaluate_node(
    course_id: str,
    node_id: str,
    req: EvaluateRequest,
    conn: DbConn,
) -> EvaluateResponse:
    course_row = resolve_course_row(conn, course_id)
    if course_row is None:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    real_course_id = course_row["id"]
    node_row = conn.execute(
        "SELECT * FROM course_nodes WHERE course_id = ? AND id = ?;",
        (real_course_id, node_id),
    ).fetchone()
    if node_row is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found in course '{course_id}'")

    eval_prompts: list[dict[str, Any]] = json.loads(node_row["eval_prompts_json"] or "[]")
    ordered_answers, answers_by_prompt = normalize_answers(req.answers, eval_prompts)

    raw_feedback = evaluate_rubric(eval_prompts, answers_by_prompt, req.covered_points)
    if req.score is not None:
        computed_score = float(req.score)
        if req.covered_points is None:
            for item in raw_feedback:
                item["covered"] = computed_score >= PASS_SCORE
    else:
        computed_score = score_from_feedback(raw_feedback)

    conn.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1);")
    prof_row = conn.execute("SELECT cooldown_mode FROM user_profile WHERE id = 1;").fetchone()
    cooldown_mode = req.cooldown_mode or (prof_row["cooldown_mode"] if prof_row else "semester")
    if req.cooldown_mode and prof_row and prof_row["cooldown_mode"] != req.cooldown_mode:
        conn.execute("UPDATE user_profile SET cooldown_mode = ? WHERE id = 1;", (req.cooldown_mode,))

    conn.execute(
        """
        INSERT OR IGNORE INTO node_progress (
            course_id, node_id, mastery_level, next_review_at, training_reps, best_score
        )
        VALUES (?, ?, 0, NULL, 0, 0);
        """,
        (real_course_id, node_id),
    )
    prog_row = conn.execute(
        "SELECT * FROM node_progress WHERE course_id = ? AND node_id = ?;",
        (real_course_id, node_id),
    ).fetchone()
    assert prog_row is not None

    now = datetime.now(UTC)
    result = apply_evaluation(
        mastery_level=int(prog_row["mastery_level"]),
        training_reps=int(prog_row["training_reps"]),
        best_score=float(prog_row["best_score"]),
        next_review_at=_parse_iso(prog_row["next_review_at"]),
        score=computed_score,
        cooldown_mode=cooldown_mode,
        now=now,
    )

    now_iso = _format_iso(now)
    next_review_iso = _format_iso(result.next_review_at)

    conn.execute(
        """
        UPDATE node_progress
        SET mastery_level = ?,
            next_review_at = ?,
            training_reps = ?,
            best_score = ?,
            last_score = ?,
            last_practiced_at = ?
        WHERE course_id = ? AND node_id = ?;
        """,
        (
            result.mastery_level,
            next_review_iso,
            result.training_reps,
            result.best_score,
            result.score,
            now_iso,
            real_course_id,
            node_id,
        ),
    )

    conn.execute(
        """
        INSERT INTO evaluation_attempts (
            course_id, node_id, answers_json, score, passed, counted_mastery, feedback_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            real_course_id,
            node_id,
            json.dumps(ordered_answers, ensure_ascii=False),
            result.score,
            1 if result.passed else 0,
            1 if result.counted_mastery else 0,
            json.dumps(raw_feedback, ensure_ascii=False),
            now_iso,
        ),
    )
    conn.commit()

    updated_progress = NodeProgress(
        node_id=node_id,
        mastery_level=result.mastery_level,
        next_review_at=next_review_iso,
        training_reps=result.training_reps,
        best_score=result.best_score,
        last_score=result.score,
        last_practiced_at=now_iso,
    )

    return EvaluateResponse(
        score=result.score,
        passed=result.passed,
        counted_mastery=result.counted_mastery,
        feedback=[PointFeedback(**f) for f in raw_feedback],
        progress=updated_progress,
    )


@router.post("/courses/{course_id}/reset-progress")
def reset_course_progress(
    course_id: str,
    conn: DbConn,
) -> dict[str, Any]:
    course_row = resolve_course_row(conn, course_id)
    if course_row is None:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    real_course_id = course_row["id"]
    conn.execute(
        """
        UPDATE node_progress
        SET mastery_level = 0,
            next_review_at = NULL,
            training_reps = 0,
            best_score = 0,
            last_score = NULL,
            last_practiced_at = NULL
        WHERE course_id = ?;
        """,
        (real_course_id,),
    )
    conn.execute("DELETE FROM evaluation_attempts WHERE course_id = ?;", (real_course_id,))
    conn.commit()
    return {"course_id": real_course_id, "reset": True}
