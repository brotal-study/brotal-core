"""Rutas locales (~/.brotal/) y lectura de keys. STUB - Issue #2.

Contrato:
- BROTAL_HOME (env, default ~/.brotal) contiene brotal.db y cache/.
- Las keys (GROQ_API_KEY, GEMINI_API_KEY, OLLAMA_URL) se leen de variables de entorno / .env.
- Nunca exponer valores de keys por API: solo si estan configuradas (bool).
"""
from pathlib import Path


def brotal_home() -> Path:
    raise NotImplementedError("Issue #2")


def db_path() -> Path:
    raise NotImplementedError("Issue #2")


def configured_providers() -> dict[str, bool]:
    """Ej: {"groq": True, "gemini": False, "ollama": False}."""
    raise NotImplementedError("Issue #2")
