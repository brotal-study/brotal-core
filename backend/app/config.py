"""Rutas locales (~/.brotal/) y lectura/escritura segura de keys (v1.0).

Contrato:
- BROTAL_HOME (env, default ~/.brotal) contiene brotal.db, .env y tts_cache/.
- Las keys (GROQ_API_KEY, GEMINI_API_KEY, OLLAMA_URL, OLLAMA_MODEL) se leen de variables de entorno
  y de ~/.brotal/.env (o .env en la raiz si existe).
- Nunca exponer valores de keys por API: solo si estan configuradas (bool) y modelos activos.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_BROTAL_HOME = Path.home() / ".brotal"
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
FALLBACK_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2"


def brotal_home() -> Path:
    raw = os.environ.get("BROTAL_HOME")
    base = Path(raw).expanduser() if raw else DEFAULT_BROTAL_HOME
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return brotal_home() / "brotal.db"


def dotenv_path() -> Path:
    return brotal_home() / ".env"


def tts_cache_dir() -> Path:
    cache = brotal_home() / "tts_cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def legacy_tts_cache_dir() -> Path:
    return brotal_home() / "cache" / "tts"


def fixtures_dir() -> Path:
    return REPO_ROOT / "fixtures"


def _read_dotenv_keys() -> dict[str, str]:
    values: dict[str, str] = {}
    for candidate in (REPO_ROOT / ".env", dotenv_path()):
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


def get_secret(key: str, default: str = "") -> str:
    """Obtiene una variable desde os.environ o desde ~/.brotal/.env (sin exponerla en endpoints)."""
    env_val = os.environ.get(key)
    if env_val is not None and env_val.strip():
        return env_val.strip()
    dotenv_vals = _read_dotenv_keys()
    val = dotenv_vals.get(key, "").strip()
    return val if val else default


def write_dotenv_keys(updates: dict[str, str | None]) -> Path:
    """Actualiza ~/.brotal/.env y fija permisos 0600."""
    target = dotenv_path()
    existing: dict[str, str] = {}
    if target.is_file():
        try:
            for line in target.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                k, v = stripped.split("=", 1)
                existing[k.strip()] = v.strip().strip("'\"")
        except OSError:
            existing = {}

    for k, v in updates.items():
        if v is None:
            continue
        cleaned = v.strip()
        if cleaned:
            existing[k] = cleaned
        else:
            existing.pop(k, None)

    lines = ["# Brotal local secrets (chmod 0600) — never commit this file"]
    for k, v in sorted(existing.items()):
        safe_val = v.replace("\n", " ").replace("\r", "")
        lines.append(f'{k}="{safe_val}"')

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


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


def provider_models() -> dict[str, str]:
    """Modelos configurados por proveedor."""
    return {
        "groq": get_secret("GROQ_MODEL", DEFAULT_GROQ_MODEL),
        "gemini": get_secret("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        "ollama": get_secret("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        "ollama_url": get_secret("OLLAMA_URL", DEFAULT_OLLAMA_URL),
    }
