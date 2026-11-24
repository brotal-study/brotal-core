"""Esquemas Pydantic v2 para el perfil local (Issue #2)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CurriculumMode = Literal["realistic", "free"]
CooldownMode = Literal["semester", "urgency"]
Theme = Literal["dark", "light"]
AiProvider = Literal["auto", "groq", "gemini", "ollama"]


class ProvidersStatus(BaseModel):
    groq: bool
    gemini: bool
    ollama: bool


class Profile(BaseModel):
    id: int = 1
    display_name: str
    career_id: str | None = None
    curriculum_mode: CurriculumMode = "realistic"
    cooldown_mode: CooldownMode = "semester"
    theme: Theme = "dark"
    ai_provider: AiProvider = "auto"
    created_at: str
    providers: ProvidersStatus


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    career_id: str | None = None
    curriculum_mode: CurriculumMode | None = None
    cooldown_mode: CooldownMode | None = None
    theme: Theme | None = None
    ai_provider: AiProvider | None = None
