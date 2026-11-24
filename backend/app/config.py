"""Rutas locales (~/.brotal/) y lectura de keys (Issue #2).

Contrato:
- BROTAL_HOME (env, default ~/.brotal) contiene brotal.db y cache/.
- Las keys (GROQ_API_KEY, GEMINI_API_KEY, OLLAMA_URL) se leen de variables de entorno / .env.
- Nunca exponer valores de keys por API: solo si estan configuradas (bool).
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_BROTAL_HOME = Path.home() / ".brotal"
REPO_ROOT = Path(__file__).resolve().parents[2]


def brotal_home() -> Path:
    raw = os.environ.get("BROTAL_HOME")
    base = Path(raw).expanduser() if raw else DEFAULT_BROTAL_HOME
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return brotal_home() / "brotal.db"


def tts_cache_dir() -> Path:
    cache = brotal_home() / "cache" / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def fixtures_dir() -> Path:
    return REPO_ROOT / "fixtures"


def _read_dotenv_keys() -> dict[str, str]:
    values: dict[str, str] = {}
    for candidate in (REPO_ROOT / ".env", brotal_home() / ".env"):
        if not candidate.is_file():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                k, v = stripped.split("=", 1)
                values[k.strip()] = v.strip().strip("'\"")
        except OSError:
            continue
    return values


def _has_env_or_dotenv(key: str, dotenv_vals: dict[str, str]) -> bool:
    val = os.environ.get(key)
    if val is not None:
        return bool(val.strip())
    return bool(dotenv_vals.get(key, "").strip())


def configured_providers() -> dict[str, bool]:
    """Devuelve solo booleanos indicando si cada proveedor tiene key/URL configurada."""
    dotenv_vals = _read_dotenv_keys()
    return {
        "groq": _has_env_or_dotenv("GROQ_API_KEY", dotenv_vals),
        "gemini": _has_env_or_dotenv("GEMINI_API_KEY", dotenv_vals),
        "ollama": _has_env_or_dotenv("OLLAMA_URL", dotenv_vals),
    }
