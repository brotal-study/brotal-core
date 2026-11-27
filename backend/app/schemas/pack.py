"""Esquemas Pydantic v2 para CoursePack y ramos (Issue #3)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.career import CourseStatus

BranchType = Literal["theory", "practice"]
EngineType = Literal["concept_tree", "code_lab", "language_studio"]
ChallengeType = Literal[
    "concept",
    "trace",
    "debug",
    "implement",
    "fill_blank",
    "translate",
    "speaking_prompt",
]
CodeLanguage = Literal["java", "sql", "python", "c", "en", "text"]

_VALID_CHALLENGE_TYPES = {
    "concept",
    "trace",
    "debug",
    "implement",
    "fill_blank",
    "translate",
    "speaking_prompt",
}
_VALID_CODE_LANGUAGES = {"java", "sql", "python", "c", "en", "text"}


class EvalPrompt(BaseModel):
    id: str
    question: str
    rubric_points: list[str] = Field(min_length=1)
    challenge_type: ChallengeType = "concept"
    language: CodeLanguage = "text"
    starter_code: str | None = None

    @field_validator("challenge_type", mode="before")
    @classmethod
    def _normalize_challenge_type(cls, v: Any) -> str:
        if isinstance(v, str) and v.strip().lower() in _VALID_CHALLENGE_TYPES:
            return v.strip().lower()
        return "concept"

    @field_validator("language", mode="before")
    @classmethod
    def _normalize_language(cls, v: Any) -> str:
        if isinstance(v, str):
            low = v.strip().lower()
            if low in ("cpp", "c++"):
                return "c"
            if low in ("english", "eng", "en-us", "en-gb", "en-au"):
                return "en"
            if low in _VALID_CODE_LANGUAGES:
                return low
        return "text"


class PackNode(BaseModel):
    id: str
    parent_ids: list[str] = Field(default_factory=list)
    branch: BranchType = "theory"
    block: str
    title: str
    summary: str
    story_script: str
    eval_prompts: list[EvalPrompt] = Field(default_factory=list)
    storyboard_ref: str | None = None


class PackMetadata(BaseModel):
    university_id: str
    career_ids: list[str] = Field(default_factory=list)
    created_year: int
    updated_year: int
    version: str
    authors: list[str] = Field(default_factory=list)
    license: str
    world_metaphor: str | None = None


class CoursePack(BaseModel):
    schema_version: Literal["1.0"]
    id: str
    course_code: str
    title: str
    language: str = "es"
    engine_type: EngineType = "concept_tree"
    metadata: PackMetadata
    nodes: list[PackNode] = Field(min_length=1)


class PackSummary(BaseModel):
    id: str
    career_ids: list[str]
    course_code: str
    title: str
    engine_type: EngineType = "concept_tree"
    created_year: int
    updated_year: int
    version: str
    metadata: PackMetadata
    node_count: int
    pack_url: str | None = None


class CourseOut(BaseModel):
    id: str
    career_id: str | None = None
    course_code: str | None = None
    code: str
    title: str
    name: str
    credits: int = 0
    category: str = "inf"
    engine_type: str = "concept_tree"
    status: CourseStatus
    source_type: Literal["pack", "local"]
    pack_version: str | None = None
    created_year: int | None = None
    updated_year: int | None = None
    manual: bool = False
    updated_at: str


class CoursePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CourseStatus | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)


class ManualCourseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, min_length=1, max_length=64)
    code: str = Field(default="LIBRE", min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    credits: int = Field(default=3, ge=0, le=30)
    category: str = Field(default="inf", min_length=1, max_length=32)
