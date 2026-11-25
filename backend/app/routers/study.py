"""Router de estudio, evaluacion socratica, regeneracion de historia y TTS (v1.0)."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.db.database import get_conn
from app.schemas.pack import EvalPrompt, PackNode
from app.schemas.study import (
    CourseTreeResponse,
    EvaluateRequest,
    EvaluateResponse,
    NodeProgress,
    PointFeedback,
    RegenerateQuestionsResponse,
    RegenerateStoryResponse,
    normalize_answers,
)
from app.services.ai_router import (
    AiProviderError,
    evaluate_with_ai,
    regenerate_questions_with_ai,
    regenerate_story_with_ai,
)
from app.services.evaluator import (
    PASS_SCORE,
    apply_evaluation,
    evaluate_rubric,
    score_from_feedback,
)
from app.services.pack_manager import resolve_course_row
from app.services.tts import (
    TtsSynthesisError,
    clear_node_tts_cache,
    get_node_tts_timings_data,
    synthesize_node_tts,
)

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


def _extract_world_metaphor(course_row: sqlite3.Row) -> str | None:
    if course_row["pack_metadata_json"]:
        try:
            meta = json.loads(course_row["pack_metadata_json"])
            if isinstance(meta, dict):
                return meta.get("world_metaphor")
        except json.JSONDecodeError:
            return None
    return None


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

    world_metaphor = _extract_world_metaphor(course_row)

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
        engine_type=course_row["engine_type"] or "concept_tree",
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

    conn.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1);")
    prof_row = conn.execute("SELECT cooldown_mode, ai_provider FROM user_profile WHERE id = 1;").fetchone()
    cooldown_mode = req.cooldown_mode or (prof_row["cooldown_mode"] if prof_row else "semester")
    ai_provider = prof_row["ai_provider"] if prof_row else "auto"
    if req.cooldown_mode and prof_row and prof_row["cooldown_mode"] != req.cooldown_mode:
        conn.execute("UPDATE user_profile SET cooldown_mode = ? WHERE id = 1;", (req.cooldown_mode,))

    imprecisions: list[str] = []
    re_explanation: str | None = None
    evaluated_by = "local_fallback"

    # Si no se inyectaron covered_points ni score explicito, intentamos evaluar con ai_router
    if req.covered_points is None and req.score is None:
        try:
            ai_res = evaluate_with_ai(
                node_title=node_row["title"],
                story_script=node_row["story_script"] or "",
                eval_prompts=eval_prompts,
                answers_by_prompt=answers_by_prompt,
                preferred_provider=ai_provider,
                engine_type=course_row["engine_type"] or "concept_tree",
            )
            raw_feedback = evaluate_rubric(eval_prompts, answers_by_prompt, ai_res["covered_points"])
            computed_score = float(ai_res["score"])
            imprecisions = list(ai_res.get("imprecisions") or [])
            re_explanation = ai_res.get("re_explanation")
            evaluated_by = str(ai_res.get("provider") or "ai")
        except (AiProviderError, ValueError, KeyError):
            raw_feedback = evaluate_rubric(eval_prompts, answers_by_prompt, None)
            computed_score = score_from_feedback(raw_feedback)
            evaluated_by = "local_fallback"
            if computed_score < PASS_SCORE:
                missed_pts = [f["point"] for f in raw_feedback if not f["covered"]]
                if missed_pts:
                    re_explanation = (
                        "Repasemos lo que falto en tu respuesta: "
                        + "; ademas, ".join(missed_pts[:3])
                        + "."
                    )
    else:
        raw_feedback = evaluate_rubric(eval_prompts, answers_by_prompt, req.covered_points)
        if req.score is not None:
            computed_score = float(req.score)
            if req.covered_points is None:
                for item in raw_feedback:
                    item["covered"] = computed_score >= PASS_SCORE
        else:
            computed_score = score_from_feedback(raw_feedback)
        if computed_score < PASS_SCORE:
            missed_pts = [f["point"] for f in raw_feedback if not f["covered"]]
            if missed_pts:
                re_explanation = (
                    "Repasemos lo que falto en tu respuesta: "
                    + "; ademas, ".join(missed_pts[:3])
                    + "."
                )

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
        imprecisions=imprecisions,
        re_explanation=re_explanation,
        evaluated_by=evaluated_by,
    )


@router.post("/study/{course_id}/{node_id}/regenerate-story", response_model=RegenerateStoryResponse)
def post_regenerate_story(
    course_id: str,
    node_id: str,
    conn: DbConn,
) -> RegenerateStoryResponse:
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

    conn.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1);")
    prof_row = conn.execute(
        "SELECT ai_provider, explanation_style FROM user_profile WHERE id = 1;"
    ).fetchone()
    ai_provider = prof_row["ai_provider"] if prof_row else "auto"
    explanation_style = (
        prof_row["explanation_style"]
        if (prof_row and "explanation_style" in set(prof_row.keys()))
        else "narrative"
    )

    eval_prompts: list[dict[str, Any]] = json.loads(node_row["eval_prompts_json"] or "[]")
    world_metaphor = _extract_world_metaphor(course_row)

    old_story = node_row["story_script"] or ""
    new_story, provider = regenerate_story_with_ai(
        course_title=course_row["title"],
        world_metaphor=world_metaphor,
        node_title=node_row["title"],
        node_summary=node_row["summary"] or "",
        current_story=old_story,
        eval_prompts=eval_prompts,
        preferred_provider=ai_provider,
        explanation_style=explanation_style,
    )

    clear_node_tts_cache(real_course_id, old_story)
    conn.execute(
        "UPDATE course_nodes SET story_script = ? WHERE course_id = ? AND id = ?;",
        (new_story, real_course_id, node_id),
    )
    conn.commit()

    return RegenerateStoryResponse(
        course_id=real_course_id,
        node_id=node_id,
        story_script=new_story,
        provider=provider,
    )


@router.post("/study/{course_id}/{node_id}/regenerate-questions", response_model=RegenerateQuestionsResponse)
def post_regenerate_questions(
    course_id: str,
    node_id: str,
    conn: DbConn,
) -> RegenerateQuestionsResponse:
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

    conn.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1);")
    prof_row = conn.execute(
        "SELECT ai_provider, question_style FROM user_profile WHERE id = 1;"
    ).fetchone()
    ai_provider = prof_row["ai_provider"] if prof_row else "auto"
    question_style = (
        prof_row["question_style"]
        if (prof_row and "question_style" in set(prof_row.keys()))
        else "direct"
    )

    eval_prompts: list[dict[str, Any]] = json.loads(node_row["eval_prompts_json"] or "[]")
    world_metaphor = _extract_world_metaphor(course_row)

    new_prompts_raw, provider = regenerate_questions_with_ai(
        course_title=course_row["title"],
        world_metaphor=world_metaphor,
        node_title=node_row["title"],
        node_summary=node_row["summary"] or "",
        story_script=node_row["story_script"] or "",
        eval_prompts=eval_prompts,
        preferred_provider=ai_provider,
        question_style=question_style,
        engine_type=course_row["engine_type"] or "concept_tree",
    )
    validated_prompts = [EvalPrompt.model_validate(p) for p in new_prompts_raw]

    conn.execute(
        "UPDATE course_nodes SET eval_prompts_json = ? WHERE course_id = ? AND id = ?;",
        (
            json.dumps([p.model_dump() for p in validated_prompts], ensure_ascii=False),
            real_course_id,
            node_id,
        ),
    )
    conn.commit()

    return RegenerateQuestionsResponse(
        course_id=real_course_id,
        node_id=node_id,
        eval_prompts=validated_prompts,
        provider=provider,
    )


@router.post("/study/{course_id}/{node_id}/tts")
async def post_node_tts(
    course_id: str,
    node_id: str,
    conn: DbConn,
    voice: str | None = None,
) -> FileResponse:
    course_row = resolve_course_row(conn, course_id)
    if course_row is None:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    real_course_id = course_row["id"]
    node_row = conn.execute(
        "SELECT story_script FROM course_nodes WHERE course_id = ? AND id = ?;",
        (real_course_id, node_id),
    ).fetchone()
    if node_row is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found in course '{course_id}'")

    story_script = (node_row["story_script"] or "").strip()
    if not story_script:
        raise HTTPException(status_code=400, detail="Node has no story_script")

    try:
        mp3_path = await synthesize_node_tts(
            course_id=real_course_id,
            text=story_script,
            voice=voice,
        )
    except TtsSynthesisError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return FileResponse(
        path=mp3_path,
        media_type="audio/mpeg",
        filename=f"{real_course_id}_{node_id}.mp3",
    )


@router.get("/study/{course_id}/{node_id}/tts-timings")
def get_node_tts_timings_endpoint(
    course_id: str,
    node_id: str,
    conn: DbConn,
    voice: str | None = None,
) -> dict[str, Any]:
    course_row = resolve_course_row(conn, course_id)
    if course_row is None:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    real_course_id = course_row["id"]
    node_row = conn.execute(
        "SELECT story_script FROM course_nodes WHERE course_id = ? AND id = ?;",
        (real_course_id, node_id),
    ).fetchone()
    if node_row is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found in course '{course_id}'")

    story_script = (node_row["story_script"] or "").strip()
    data = get_node_tts_timings_data(
        course_id=real_course_id,
        text=story_script,
        voice=voice,
    )
    return {
        "course_id": real_course_id,
        "node_id": node_id,
        "sentences": data["sentences"],
        "words": data["words"],
        "timings": data["sentences"],
    }


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
