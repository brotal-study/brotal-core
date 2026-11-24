"""Esquemas Pydantic v2 para CoursePack y ramos (Issue #3)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.career import CourseStatus

BranchType = Literal["theory", "practice"]
EngineType = Literal["concept_tree", "code_lab", "language_studio"]


class EvalPrompt(BaseModel):
    id: str
    question: str
    rubric_points: list[str] = Field(min_length=1)


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
