"""Esquemas Pydantic v2 para arbol de estudio y evaluacion 7/10 (v1.0)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.pack import EvalPrompt, PackNode
from app.schemas.profile import CooldownMode


class NodeProgress(BaseModel):
    node_id: str
    mastery_level: int = Field(default=0, ge=0, le=3)
    next_review_at: str | None = None
    training_reps: int = Field(default=0, ge=0)
    best_score: float = Field(default=0.0, ge=0.0, le=10.0)
    last_score: float | None = None
    last_practiced_at: str | None = None


class CourseTreeResponse(BaseModel):
    course_id: str
    course_code: str
    title: str
    world_metaphor: str | None = None
    nodes: list[PackNode]
    progress: dict[str, NodeProgress]


class AnswerItem(BaseModel):
    prompt_id: str
    text: str = ""


class EvaluateRequest(BaseModel):
    answers: list[AnswerItem] | list[str] | dict[str, str] = Field(default_factory=list)
    cooldown_mode: CooldownMode | None = None
    covered_points: list[str] | None = None
    score: float | None = Field(default=None, ge=1.0, le=10.0)


class PointFeedback(BaseModel):
    prompt_id: str
    point_index: int
    point: str
    covered: bool


class EvaluateResponse(BaseModel):
    score: float
    passed: bool
    counted_mastery: bool
    feedback: list[PointFeedback]
    progress: NodeProgress
    imprecisions: list[str] = Field(default_factory=list)
    re_explanation: str | None = None
    evaluated_by: str = "local_fallback"


class RegenerateStoryResponse(BaseModel):
    course_id: str
    node_id: str
    story_script: str
    provider: str


class RegenerateQuestionsResponse(BaseModel):
    course_id: str
    node_id: str
    eval_prompts: list[EvalPrompt]
    provider: str


def normalize_answers(
    raw_answers: list[AnswerItem] | list[str] | dict[str, str] | Any,
    eval_prompts: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Convierte answers en (lista ordenada recibida, mapa prompt_id -> texto)."""
    ordered: list[dict[str, str]] = []
    by_prompt: dict[str, str] = {}

    if isinstance(raw_answers, dict):
        for k, v in raw_answers.items():
            ordered.append({"prompt_id": str(k), "text": str(v)})
            by_prompt[str(k)] = str(v)
    elif isinstance(raw_answers, list):
        for idx, item in enumerate(raw_answers):
            if isinstance(item, AnswerItem):
                ordered.append({"prompt_id": item.prompt_id, "text": item.text})
                by_prompt[item.prompt_id] = item.text
            elif isinstance(item, dict):
                pid = str(item.get("prompt_id") or item.get("id") or (eval_prompts[idx]["id"] if idx < len(eval_prompts) else f"q{idx+1}"))
                txt = str(item.get("text") or item.get("answer") or "")
                ordered.append({"prompt_id": pid, "text": txt})
                by_prompt[pid] = txt
            else:
                pid = str(eval_prompts[idx]["id"]) if idx < len(eval_prompts) else f"q{idx+1}"
                txt = str(item)
                ordered.append({"prompt_id": pid, "text": txt})
                by_prompt[pid] = txt

    return ordered, by_prompt
