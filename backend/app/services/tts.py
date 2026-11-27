"""Sintesis de voz neural con edge-tts, marcas de tiempo por oracion y cache en disco (v1.0.2).

Contrato:
- Cache en ~/.brotal/tts_cache/{course_id}/{hash}.mp3 y {hash}.timings.json (respeta BROTAL_HOME).
- Voces neurales en espanol con fallback automatico:
  es-CL-LorenzoNeural -> es-MX-JorgeNeural -> es-ES-AlvaroNeural.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.config import tts_cache_dir

DEFAULT_VOICES = (
    "es-CL-LorenzoNeural",
    "es-MX-JorgeNeural",
    "es-ES-AlvaroNeural",
)


class TtsSynthesisError(RuntimeError):
    """Error al sintetizar audio con edge-tts."""


def strip_code_blocks_and_markdown_for_tts(text: str) -> str:
    """Elimina bloques cercados ```...``` y marcadores ** y ` para que TTS sintetice solo la prosa."""
    if not text:
        return ""
    without_fences = re.sub(r"```[\s\S]*?```", "\n\n", text)
    without_fences = re.sub(r"```[\s\S]*$", "", without_fences)
    without_md = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", without_fences)
    without_md = without_md.replace("**", "")
    without_md = re.sub(r"`([^`\n]+)`", r"\1", without_md)
    without_md = without_md.replace("`", "")

    paragraphs: list[str] = []
    for raw_p in re.split(r"\n{2,}", without_md):
        clean_p = re.sub(r"[ \t]+", " ", raw_p).strip()
        if clean_p:
            paragraphs.append(clean_p)
    return "\n\n".join(paragraphs)


def compute_tts_hash(text: str, voice: str) -> str:
    narrated = strip_code_blocks_and_markdown_for_tts(text) or text.strip()
    payload = f"{voice}::{narrated}".encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def cached_tts_path(course_id: str, text: str, voice: str = DEFAULT_VOICES[0]) -> Path:
    safe_course = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in course_id) or "default"
    course_dir = tts_cache_dir() / safe_course
    course_dir.mkdir(parents=True, exist_ok=True)
    h = compute_tts_hash(text, voice)
    return course_dir / f"{h}.mp3"


def cached_tts_timings_path(course_id: str, text: str, voice: str = DEFAULT_VOICES[0]) -> Path:
    return cached_tts_path(course_id, text, voice).with_suffix(".timings.json")


def split_story_sentences(text: str) -> list[str]:
    """Divide story_script en oraciones (solo prosa sin bloques de codigo) preservando el orden de los parrafos."""
    prose = strip_code_blocks_and_markdown_for_tts(text)
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", prose) if p.strip()]
    sentences: list[str] = []
    for p in paragraphs:
        parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()]
        sentences.extend(parts if parts else [p])
    return sentences


def _ticks_to_seconds(val: float) -> float:
    fval = float(val)
    if fval >= 10_000:
        return round(fval / 10_000_000.0, 3)
    return round(fval, 3)


def _group_word_boundaries_into_sentences(
    text: str,
    word_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not word_events:
        return []
    target_sentences = split_story_sentences(text)
    if not target_sentences:
        return []

    total_chars = max(1, sum(len(s) for s in target_sentences))
    total_words = len(word_events)
    grouped: list[dict[str, Any]] = []
    word_cursor = 0

    for idx, sent in enumerate(target_sentences):
        if word_cursor >= total_words:
            break
        if idx == len(target_sentences) - 1:
            slice_words = word_events[word_cursor:]
        else:
            approx_count = max(1, round((len(sent) / total_chars) * total_words))
            end_cursor = min(total_words, word_cursor + approx_count)
            # Intentar cortar en palabra cercana si coincide con el final de la oracion
            slice_words = word_events[word_cursor:end_cursor]
            word_cursor = end_cursor

        if slice_words:
            start_sec = float(slice_words[0]["start"])
            end_sec = float(slice_words[-1]["end"])
            if end_sec <= start_sec:
                end_sec = round(start_sec + 0.25, 3)
            grouped.append(
                {
                    "text": sent,
                    "start": round(start_sec, 3),
                    "end": round(end_sec, 3),
                }
            )

    return grouped


def _derive_words_from_sentences(
    text: str,
    sentence_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Deriva tiempos proporcionales por palabra dentro de cada oracion cuando edge-tts no emite WordBoundary."""
    target_sentences = split_story_sentences(text)
    if not target_sentences:
        return []

    if len(sentence_events) == len(target_sentences):
        source_sentences = [
            {
                "text": target_sentences[i],
                "start": float(sentence_events[i].get("start", 0.0)),
                "end": float(sentence_events[i].get("end", 0.0)),
            }
            for i in range(len(target_sentences))
        ]
    elif sentence_events:
        total_end = max(float(sentence_events[-1].get("end", 0.0)), len(target_sentences) * 2.5)
        total_chars = max(1, sum(len(s) for s in target_sentences))
        cursor = 0.0
        source_sentences = []
        for idx, s in enumerate(target_sentences):
            dur = (len(s) / total_chars) * total_end
            end_t = total_end if idx == len(target_sentences) - 1 else round(cursor + dur, 3)
            source_sentences.append({"text": s, "start": round(cursor, 3), "end": max(round(cursor + 0.1, 3), end_t)})
            cursor = end_t
    else:
        cursor = 0.0
        source_sentences = []
        for s in target_sentences:
            tokens = [w for w in s.split() if w]
            dur = max(0.8, len(tokens) * 0.34)
            end_t = round(cursor + dur, 3)
            source_sentences.append({"text": s, "start": round(cursor, 3), "end": end_t})
            cursor = end_t

    words_out: list[dict[str, Any]] = []
    for sent in source_sentences:
        s_text = str(sent["text"]).strip()
        tokens = [w for w in re.split(r"\s+", s_text) if w]
        if not tokens:
            continue
        s_start = float(sent["start"])
        s_end = max(s_start + 0.1, float(sent["end"]))
        s_dur = s_end - s_start
        weights = [max(1, len(t)) for t in tokens]
        total_w = sum(weights)
        acc = 0
        for idx, (tok, w) in enumerate(zip(tokens, weights, strict=True)):
            w_start = s_start + (acc / total_w) * s_dur
            acc += w
            w_end = s_end if idx == len(tokens) - 1 else s_start + (acc / total_w) * s_dur
            words_out.append(
                {
                    "text": tok,
                    "start": round(w_start, 3),
                    "end": round(max(w_start + 0.04, w_end), 3),
                }
            )
    return words_out


async def _run_edge_tts(text: str, voice: str, out_path: Path) -> dict[str, list[dict[str, Any]]]:
    import edge_tts  # type: ignore[import-untyped]

    communicate = edge_tts.Communicate(text=text, voice=voice)
    audio_chunks: list[bytes] = []
    sentence_events: list[dict[str, Any]] = []
    word_events: list[dict[str, Any]] = []

    async for chunk in communicate.stream():
        ctype = chunk.get("type")
        if ctype == "audio":
            data = chunk.get("data")
            if isinstance(data, (bytes, bytearray)):
                audio_chunks.append(bytes(data))
        elif ctype in ("SentenceBoundary", "WordBoundary"):
            offset = _ticks_to_seconds(chunk.get("offset", 0))
            duration = _ticks_to_seconds(chunk.get("duration", 0))
            end_sec = round(offset + max(0.05, duration), 3)
            ev = {
                "text": str(chunk.get("text") or "").strip(),
                "start": offset,
                "end": end_sec,
            }
            if ctype == "SentenceBoundary" and ev["text"]:
                sentence_events.append(ev)
            elif ctype == "WordBoundary" and ev["text"]:
                word_events.append(ev)

    if audio_chunks:
        out_path.write_bytes(b"".join(audio_chunks))

    sentences = (
        sentence_events
        if sentence_events
        else _group_word_boundaries_into_sentences(text, word_events)
    )
    words = word_events if word_events else _derive_words_from_sentences(text, sentences)
    return {"sentences": sentences, "words": words}


def _normalize_timings_payload(text: str, raw: Any) -> dict[str, list[dict[str, Any]]]:
    """Normaliza tanto caches antiguos (lista de sentences) como nuevos ({sentences, words})."""
    sentences: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []

    if isinstance(raw, list):
        sentences = [x for x in raw if isinstance(x, dict)]
    elif isinstance(raw, dict):
        raw_s = raw.get("sentences")
        raw_w = raw.get("words")
        if isinstance(raw_s, list):
            sentences = [x for x in raw_s if isinstance(x, dict)]
        if isinstance(raw_w, list):
            words = [x for x in raw_w if isinstance(x, dict)]

    if not sentences and words:
        sentences = _group_word_boundaries_into_sentences(text, words)
    if not words:
        words = _derive_words_from_sentences(text, sentences)

    return {"sentences": sentences, "words": words}


async def synthesize_node_tts(
    *,
    course_id: str,
    text: str,
    voice: str | None = None,
) -> Path:
    """Devuelve la ruta al MP3 en cache (y guarda .timings.json con sentences y words), o lo sintetiza con edge-tts."""
    cleaned = strip_code_blocks_and_markdown_for_tts(text)
    if not cleaned:
        raise TtsSynthesisError("El nodo no tiene story_script para sintetizar.")

    voices_to_try = [voice] if voice else list(DEFAULT_VOICES)
    primary_voice = voices_to_try[0]
    target_path = cached_tts_path(course_id, cleaned, primary_voice)
    timings_path = cached_tts_timings_path(course_id, cleaned, primary_voice)
    if target_path.is_file() and target_path.stat().st_size > 0:
        if not timings_path.is_file():
            fallback_payload = _normalize_timings_payload(cleaned, {})
            timings_path.write_text(json.dumps(fallback_payload, ensure_ascii=False), encoding="utf-8")
        return target_path

    last_err: Exception | None = None
    tmp_path = target_path.with_suffix(".tmp.mp3")
    for candidate_voice in voices_to_try:
        try:
            timings_result = await _run_edge_tts(cleaned, candidate_voice, tmp_path)
            if tmp_path.is_file() and tmp_path.stat().st_size > 0:
                tmp_path.replace(target_path)
                normalized = _normalize_timings_payload(cleaned, timings_result)
                timings_path.write_text(
                    json.dumps(normalized, ensure_ascii=False),
                    encoding="utf-8",
                )
                return target_path
            raise TtsSynthesisError("edge-tts genero un archivo vacio")
        except (OSError, RuntimeError, ValueError, TtsSynthesisError) as exc:
            last_err = exc
            tmp_path.unlink(missing_ok=True)
            continue

    raise TtsSynthesisError(f"No se pudo sintetizar audio edge-tts: {last_err}") from last_err


def get_node_tts_timings_data(
    *,
    course_id: str,
    text: str,
    voice: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Devuelve {'sentences': [...], 'words': [...]} asegurando que words nunca quede vacio."""
    cleaned = strip_code_blocks_and_markdown_for_tts(text)
    if not cleaned:
        return {"sentences": [], "words": []}
    voices_to_try = [voice] if voice else list(DEFAULT_VOICES)
    for candidate_voice in voices_to_try:
        t_path = cached_tts_timings_path(course_id, cleaned, candidate_voice)
        if t_path.is_file():
            try:
                loaded = json.loads(t_path.read_text(encoding="utf-8"))
                return _normalize_timings_payload(cleaned, loaded)
            except json.JSONDecodeError:
                break
    return _normalize_timings_payload(cleaned, {})


def get_node_tts_timings(
    *,
    course_id: str,
    text: str,
    voice: str | None = None,
) -> list[dict[str, Any]]:
    """Devuelve las marcas de tiempo sincronizadas por oracion [{text, start, end}]."""
    return get_node_tts_timings_data(course_id=course_id, text=text, voice=voice)["sentences"]


def clear_node_tts_cache(course_id: str, text: str | None = None) -> None:
    """Elimina archivos .mp3 y .timings.json en cache al regenerar una historia."""
    if not text or not text.strip():
        return
    cleaned = strip_code_blocks_and_markdown_for_tts(text) or text.strip()
    for candidate_voice in DEFAULT_VOICES:
        mp3_file = cached_tts_path(course_id, cleaned, candidate_voice)
        timings_file = cached_tts_timings_path(course_id, cleaned, candidate_voice)
        mp3_file.unlink(missing_ok=True)
        timings_file.unlink(missing_ok=True)
