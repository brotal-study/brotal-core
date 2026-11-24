"""Router de configuracion de proveedores IA /api/v1/settings/providers (v1.0).

Contrato:
- GET /api/v1/settings/providers: devuelve solo booleanos + proveedor seleccionado + modelo activo (nunca las keys).
- PUT /api/v1/settings/providers: guarda keys en ~/.brotal/.env con permisos 0600 y actualiza ai_provider en SQLite.
"""
from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.config import configured_providers, provider_models, write_dotenv_keys
from app.db.database import get_conn
from app.schemas.profile import AiProvider, ProvidersStatus
from app.services.ai_router import resolve_active_model

router = APIRouter(tags=["settings"])

DbConn = Annotated[sqlite3.Connection, Depends(get_conn)]


class ProvidersModels(BaseModel):
    groq: str
    gemini: str
    ollama: str
    ollama_url: str


class ProvidersSettingsResponse(BaseModel):
    ai_provider: AiProvider
    active_provider: str
    active_model: str
    providers: ProvidersStatus
    models: ProvidersModels


class ProvidersSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai_provider: AiProvider | None = None
    groq_api_key: str | None = Field(default=None, max_length=512)
    gemini_api_key: str | None = Field(default=None, max_length=512)
    ollama_url: str | None = Field(default=None, max_length=256)
    groq_model: str | None = Field(default=None, max_length=128)
    gemini_model: str | None = Field(default=None, max_length=128)
    ollama_model: str | None = Field(default=None, max_length=128)


def _build_settings_response(conn: sqlite3.Connection) -> ProvidersSettingsResponse:
    conn.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1);")
    row = conn.execute("SELECT ai_provider FROM user_profile WHERE id = 1;").fetchone()
    ai_provider: AiProvider = row["ai_provider"] if row else "auto"
    active_provider, active_model = resolve_active_model(ai_provider)
    return ProvidersSettingsResponse(
        ai_provider=ai_provider,
        active_provider=active_provider,
        active_model=active_model,
        providers=ProvidersStatus(**configured_providers()),
        models=ProvidersModels(**provider_models()),
    )


@router.get("/settings/providers", response_model=ProvidersSettingsResponse)
def get_providers_settings(conn: DbConn) -> ProvidersSettingsResponse:
    return _build_settings_response(conn)


@router.put("/settings/providers", response_model=ProvidersSettingsResponse)
def put_providers_settings(
    body: ProvidersSettingsUpdate,
    conn: DbConn,
) -> ProvidersSettingsResponse:
    env_updates: dict[str, str | None] = {}
    if "groq_api_key" in body.model_fields_set:
        env_updates["GROQ_API_KEY"] = body.groq_api_key or ""
    if "gemini_api_key" in body.model_fields_set:
        env_updates["GEMINI_API_KEY"] = body.gemini_api_key or ""
    if "ollama_url" in body.model_fields_set:
        env_updates["OLLAMA_URL"] = body.ollama_url or ""
    if "groq_model" in body.model_fields_set and body.groq_model is not None:
        env_updates["GROQ_MODEL"] = body.groq_model
    if "gemini_model" in body.model_fields_set and body.gemini_model is not None:
        env_updates["GEMINI_MODEL"] = body.gemini_model
    if "ollama_model" in body.model_fields_set and body.ollama_model is not None:
        env_updates["OLLAMA_MODEL"] = body.ollama_model

    if env_updates:
        write_dotenv_keys(env_updates)

    if body.ai_provider is not None:
        conn.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1);")
        conn.execute("UPDATE user_profile SET ai_provider = ? WHERE id = 1;", (body.ai_provider,))
        conn.commit()

    return _build_settings_response(conn)
