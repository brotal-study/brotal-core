"""Esquemas Pydantic v2 para arbol de estudio y evaluacion 7/10 (v1.0)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    engine_type: str = "concept_tree"
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


class CodeFixItem(BaseModel):
    broken_snippet: str
    fixed_snippet: str
    why: str


class PromptReviewItem(BaseModel):
    prompt_id: str
    status: Literal["passed", "partial", "failed"] = "partial"
    diagnosis: str
    code_fixes: list[CodeFixItem] = Field(default_factory=list)
    corrected_solution: str | None = None


class EvaluateResponse(BaseModel):
    score: float
    passed: bool
    counted_mastery: bool
    feedback: list[PointFeedback]
    progress: NodeProgress
    imprecisions: list[str] = Field(default_factory=list)
    re_explanation: str | None = None
    evaluated_by: str = "local_fallback"
    prompt_reviews: list[PromptReviewItem] = Field(default_factory=list)
    routing_suggestion: str | None = None


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


class PhraseTtsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=1200)
    lang: Literal["en", "es"] = "en"
    accent: Literal["us", "gb", "au"] = "us"


class ExamRouteRequest(BaseModel):
    exam_date: str = Field(..., min_length=8, max_length=32)
    hours_per_day: float = Field(default=3.0, ge=0.5, le=14.0)
    goal: str = Field(default="", max_length=400)
    exam_topics: str = Field(default="", max_length=4000)


class ExamRouteStep(BaseModel):
    node_id: str | None = None
    node_title: str
    branch: str = "theory"
    action: str = "study_and_eval"
    target_mastery: int = Field(default=1, ge=1, le=3)
    estimated_minutes: int = Field(default=35, ge=5, le=240)
    reason: str = ""


class ExamRouteDay(BaseModel):
    day_label: str
    date: str
    focus: str
    steps: list[ExamRouteStep] = Field(default_factory=list)


class ExamRouteResponse(BaseModel):
    course_id: str
    course_title: str
    exam_date: str
    days_left: int
    hours_per_day: float
    goal: str = ""
    exam_topics: str = ""
    strategy_summary: str
    recommended_cooldown_mode: CooldownMode = "urgency"
    days: list[ExamRouteDay] = Field(default_factory=list)
    uncovered_topics: list[str] = Field(default_factory=list)
    provider: str = "local_fallback"
    updated_at: str


StoryboardVariant = Literal[
    "execution_trace",
    "oop_dispatch",
    "error_contrast",
    "data_structure",
    "sql_pipeline",
]


class StoryboardSubgoal(BaseModel):
    id: str
    label: str


class StoryboardCheckpoint(BaseModel):
    enabled: bool = False
    question: str = ""
    options: list[str] = Field(default_factory=list)
    correct_index: int = 0
    explanation: str = ""


class StoryboardStep(BaseModel):
    index: int
    subgoal_id: str
    active_lines: list[int] = Field(default_factory=list)
    caption: str
    sentence_index: int | None = None
    checkpoint: StoryboardCheckpoint | None = None
    state: dict[str, Any] = Field(default_factory=dict)


class NodeStoryboardResponse(BaseModel):
    course_id: str
    node_id: str
    variant: StoryboardVariant
    language: str = "java"
    title: str
    source_code: str
    fixed_code: str | None = None
    subgoals: list[StoryboardSubgoal] = Field(default_factory=list)
    steps: list[StoryboardStep] = Field(default_factory=list)
    provider: str = "local_fallback"
    updated_at: str


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
