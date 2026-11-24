"""Sintesis de voz neural con edge-tts y cache en disco (v1.0).

Contrato:
- Cache en ~/.brotal/tts_cache/{course_id}/{hash}.mp3 (respeta BROTAL_HOME).
- Voces neurales en espanol con fallback automatico:
  es-CL-LorenzoNeural -> es-MX-JorgeNeural -> es-ES-AlvaroNeural.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import tts_cache_dir

DEFAULT_VOICES = (
    "es-CL-LorenzoNeural",
    "es-MX-JorgeNeural",
    "es-ES-AlvaroNeural",
)


class TtsSynthesisError(RuntimeError):
    """Error al sintetizar audio con edge-tts."""


def compute_tts_hash(text: str, voice: str) -> str:
    payload = f"{voice}::{text.strip()}".encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def cached_tts_path(course_id: str, text: str, voice: str = DEFAULT_VOICES[0]) -> Path:
    safe_course = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in course_id) or "default"
    course_dir = tts_cache_dir() / safe_course
    course_dir.mkdir(parents=True, exist_ok=True)
    h = compute_tts_hash(text, voice)
    return course_dir / f"{h}.mp3"


async def _run_edge_tts(text: str, voice: str, out_path: Path) -> None:
    import edge_tts  # type: ignore[import-untyped]

    communicate = edge_tts.Communicate(text=text, voice=voice)
    await communicate.save(str(out_path))


async def synthesize_node_tts(
    *,
    course_id: str,
    text: str,
    voice: str | None = None,
) -> Path:
    """Devuelve la ruta al MP3 en cache, o lo sintetiza con edge-tts si no existe."""
    cleaned = text.strip()
    if not cleaned:
        raise TtsSynthesisError("El nodo no tiene story_script para sintetizar.")

    voices_to_try = [voice] if voice else list(DEFAULT_VOICES)
    primary_voice = voices_to_try[0]
    target_path = cached_tts_path(course_id, cleaned, primary_voice)
    if target_path.is_file() and target_path.stat().st_size > 0:
        return target_path

    last_err: Exception | None = None
    tmp_path = target_path.with_suffix(".tmp.mp3")
    for candidate_voice in voices_to_try:
        try:
            await _run_edge_tts(cleaned, candidate_voice, tmp_path)
            if tmp_path.is_file() and tmp_path.stat().st_size > 0:
                tmp_path.replace(target_path)
                return target_path
            raise TtsSynthesisError("edge-tts genero un archivo vacio")
        except (OSError, RuntimeError, ValueError, TtsSynthesisError) as exc:
            last_err = exc
            tmp_path.unlink(missing_ok=True)
            continue

    raise TtsSynthesisError(f"No se pudo sintetizar audio edge-tts: {last_err}") from last_err
