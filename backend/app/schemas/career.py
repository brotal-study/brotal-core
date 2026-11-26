"""Esquemas Pydantic v2 para CareerManifest y endpoints de malla (Issue #3)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CourseStatus = Literal["pending", "active", "passed", "archived"]


class UniversityInfo(BaseModel):
    id: str
    name: str
    short_name: str


class CareerInfo(BaseModel):
    name: str
    plan_year: int
    plan_ref: str | None = None
    updated_at: str


class Category(BaseModel):
    id: str
    label: str
    color: str


class CareerCourse(BaseModel):
    code: str
    name: str
    credits: int = Field(ge=0)
    category: str
    prerequisites: list[str] = Field(default_factory=list)
    optional: bool = False
    status: CourseStatus | None = None


class Semester(BaseModel):
    number: int = Field(ge=1)
    label: str
    courses: list[CareerCourse]


class CareerManifest(BaseModel):
    schema_version: Literal["1.0"]
    id: str
    country: str
    university: UniversityInfo
    career: CareerInfo
    categories: list[Category]
    semesters: list[Semester]


class CourseProgressSummary(BaseModel):
    mastered: int = 0
    total: int = 0
    started: int = 0


class CareerDetailResponse(CareerManifest):
    statuses: dict[str, CourseStatus] = Field(default_factory=dict)
    installed_packs: dict[str, str] = Field(default_factory=dict)
    course_progress: dict[str, CourseProgressSummary] = Field(default_factory=dict)
    credits_total: int = 0
    credits_passed: int = 0
    credits_approved: int = 0
    courses_total: int = 0
    courses_passed: int = 0


class BulkStatusRequest(BaseModel):
    up_to_semester: int = Field(ge=1, le=30)
    status: CourseStatus = "passed"


class BulkStatusResponse(BaseModel):
    career_id: str
    up_to_semester: int
    status: CourseStatus
    updated_count: int
    changed: int


class CareerSummary(BaseModel):
    id: str
    country: str
    university: str
    university_short: str
    career_name: str
    name: str
    plan_year: int
    plan_ref: str | None = None
    manifest_url: str | None = None
