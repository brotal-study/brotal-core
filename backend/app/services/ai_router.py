"""Pool multi-IA gratuito (Groq, Gemini Free, Ollama local) con rotacion y fallback (v1.0).

Soporta:
- Groq: llama-3.3-70b-versatile / fallback openai/gpt-oss-120b
- Gemini Free: gemini-2.5-flash (Google Generative Language REST API)
- Ollama local: http://127.0.0.1:11434 (o OLLAMA_URL configurado)
- Modo 'auto': prueba en orden los proveedores configurados y disponibles.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GROQ_MODEL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    FALLBACK_GROQ_MODEL,
    configured_providers,
    get_secret,
)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class AiProviderError(RuntimeError):
    """Error al invocar un proveedor de IA o cuando ninguno esta disponible."""


@dataclass
class AiCompletion:
    text: str
    provider: str
    model: str


def extract_json_object(raw: str) -> dict[str, Any]:
    """Extrae el primer objeto JSON valido desde una respuesta LLM (con o sin fences markdown)."""
    cleaned = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise TypeError("Expected a JSON object from AI response")
    return parsed


def call_groq(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.3,
    timeout: float = 35.0,
) -> AiCompletion:
    api_key = get_secret("GROQ_API_KEY")
    if not api_key:
        raise AiProviderError("GROQ_API_KEY no configurada")

    primary = model or get_secret("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    models_to_try = [primary]
    if FALLBACK_GROQ_MODEL not in models_to_try:
        models_to_try.append(FALLBACK_GROQ_MODEL)

    last_err: Exception | None = None
    for candidate_model in models_to_try:
        payload: dict[str, Any] = {
            "model": candidate_model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = httpx.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = str(data["choices"][0]["message"]["content"]).strip()
            if not content:
                raise AiProviderError("Groq devolvio respuesta vacia")
            return AiCompletion(text=content, provider="groq", model=candidate_model)
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError, AiProviderError) as exc:
            last_err = exc
            continue

    raise AiProviderError(f"Groq fallo: {last_err}") from last_err


def call_gemini(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.3,
    timeout: float = 35.0,
) -> AiCompletion:
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        raise AiProviderError("GEMINI_API_KEY no configurada")

    chosen_model = model or get_secret("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(content)
        else:
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": content}]})

    if not contents:
        contents.append({"role": "user", "parts": [{"text": "\n".join(system_parts)}]})
        system_parts = []

    gen_config: dict[str, Any] = {"temperature": temperature}
    if json_mode:
        gen_config["responseMimeType"] = "application/json"

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": gen_config,
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

    url = f"{GEMINI_API_BASE}/{chosen_model}:generateContent"
    try:
        resp = httpx.post(
            url,
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(str(p.get("text", "")) for p in parts).strip()
        if not text:
            raise AiProviderError("Gemini devolvio respuesta vacia")
        return AiCompletion(text=text, provider="gemini", model=chosen_model)
    except Exception as exc:
        raise AiProviderError(f"Gemini fallo: {exc}") from exc


def call_ollama(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.3,
    timeout: float = 45.0,
) -> AiCompletion:
    base_url = get_secret("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/")
    chosen_model = model or get_secret("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)

    payload: dict[str, Any] = {
        "model": chosen_model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if json_mode:
        payload["format"] = "json"

    try:
        resp = httpx.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        text = str(data.get("message", {}).get("content", "")).strip()
        if not text:
            raise AiProviderError("Ollama devolvio respuesta vacia")
        return AiCompletion(text=text, provider="ollama", model=chosen_model)
    except Exception as exc:
        raise AiProviderError(f"Ollama fallo: {exc}") from exc


def resolve_active_model(preferred_provider: str = "auto") -> tuple[str, str]:
    """Devuelve (proveedor_efectivo, modelo_activo) segun configuracion actual."""
    status = configured_providers()
    order = _provider_order(preferred_provider, status)
    if not order:
        return ("none", "local-fallback")
    first = order[0]
    if first == "groq":
        return ("groq", get_secret("GROQ_MODEL", DEFAULT_GROQ_MODEL))
    if first == "gemini":
        return ("gemini", get_secret("GEMINI_MODEL", DEFAULT_GEMINI_MODEL))
    if first == "ollama":
        return ("ollama", get_secret("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL))
    return ("none", "local-fallback")


def _provider_order(preferred: str, status: dict[str, bool]) -> list[str]:
    if preferred in ("groq", "gemini", "ollama"):
        # Primero el elegido; luego fallback a los configurados
        rest = [p for p in ("groq", "gemini", "ollama") if p != preferred and status.get(p)]
        if status.get(preferred) or preferred == "ollama":
            return [preferred, *rest]
        return rest
    # Modo 'auto': prioriza los configurados en orden groq -> gemini -> ollama
    return [p for p in ("groq", "gemini", "ollama") if status.get(p)]


def complete_chat(
    messages: list[dict[str, str]],
    *,
    preferred_provider: str = "auto",
    json_mode: bool = False,
    temperature: float = 0.3,
) -> AiCompletion:
    """Ejecuta una completacion rotando entre los proveedores gratuitos disponibles."""
    status = configured_providers()
    order = _provider_order(preferred_provider, status)
    if not order:
        raise AiProviderError("No hay proveedores IA configurados (configura Groq, Gemini u Ollama)")

    errors: list[str] = []
    for provider in order:
        try:
            if provider == "groq":
                return call_groq(messages, json_mode=json_mode, temperature=temperature)
            if provider == "gemini":
                return call_gemini(messages, json_mode=json_mode, temperature=temperature)
            if provider == "ollama":
                return call_ollama(messages, json_mode=json_mode, temperature=temperature)
        except (AiProviderError, httpx.HTTPError, ValueError, TypeError) as exc:
            errors.append(f"{provider}: {exc}")
            continue

    raise AiProviderError("Todos los proveedores IA fallaron: " + " | ".join(errors))


def evaluate_with_ai(
    *,
    node_title: str,
    story_script: str,
    eval_prompts: list[dict[str, Any]],
    answers_by_prompt: dict[str, str],
    preferred_provider: str = "auto",
) -> dict[str, Any]:
    """Evalua respuestas a ciegas con rigor socratico 1..10 usando el router multi-IA.

    Devuelve dict con:
    - score: float (1.0 .. 10.0)
    - covered_points: list[str] (formato "q1::0")
    - missing_summary: list[str]
    - imprecisions: list[str]
    - re_explanation: str | None (si score < 7.0)
    - provider: str
    - model: str
    """
    rubric_spec: list[dict[str, Any]] = []
    all_keys: list[str] = []
    for q in eval_prompts:
        qid = str(q["id"])
        pts = []
        for idx, pt in enumerate(q.get("rubric_points", [])):
            key = f"{qid}::{idx}"
            all_keys.append(key)
            pts.append({"key": key, "criterion": pt})
        rubric_spec.append(
            {
                "prompt_id": qid,
                "question": q.get("question", ""),
                "student_answer": answers_by_prompt.get(qid, "").strip(),
                "rubric_points": pts,
            }
        )

    system_prompt = (
        "Eres el Evaluador Socratico de Brotal. Evaluas respuestas a ciegas de un estudiante universitario "
        "con rigor del 1.0 al 10.0 (7.0 o mas aprueba). No regales puntos si la respuesta es vaga o vacia. "
        "Responde UNICAMENTE un objeto JSON valido con esta estructura exacta:\n"
        "{\n"
        '  "score": 7.5,\n'
        '  "covered_points": ["q1::0", "q1::1"],\n'
        '  "imprecisions": ["Confunde X con Y"],\n'
        '  "re_explanation": "Breve re-explicacion conversada (solo si score < 7.0, vacio si >= 7.0)"\n'
        "}"
    )
    user_prompt = json.dumps(
        {
            "node_title": node_title,
            "reference_story": story_script[:2000],
            "evaluation_items": rubric_spec,
        },
        ensure_ascii=False,
    )

    completion = complete_chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        preferred_provider=preferred_provider,
        json_mode=True,
        temperature=0.1,
    )

    parsed = extract_json_object(completion.text)
    valid_keys = set(all_keys)
    raw_covered = parsed.get("covered_points") or []
    covered_points = [str(k) for k in raw_covered if str(k) in valid_keys]

    raw_score = parsed.get("score")
    if isinstance(raw_score, (int, float)):
        score = round(max(1.0, min(10.0, float(raw_score))), 1)
    else:
        ratio = len(covered_points) / len(all_keys) if all_keys else 0.0
        score = round(1.0 + 9.0 * ratio, 1)

    imprecisions = [str(x).strip() for x in (parsed.get("imprecisions") or []) if str(x).strip()]
    re_exp_raw = str(parsed.get("re_explanation") or "").strip()
    re_explanation = re_exp_raw if (score < 7.0 and re_exp_raw) else None

    if score < 7.0 and not re_explanation:
        missed_texts = [
            pt["criterion"]
            for item in rubric_spec
            for pt in item["rubric_points"]
            if pt["key"] not in covered_points
        ]
        if missed_texts:
            re_explanation = (
                "Pensemoslo de nuevo con calma: te falto conectar que "
                + "; ademas, ".join(missed_texts[:3])
                + "."
            )

    return {
        "score": score,
        "covered_points": covered_points,
        "imprecisions": imprecisions,
        "re_explanation": re_explanation,
        "provider": completion.provider,
        "model": completion.model,
    }


def regenerate_story_with_ai(
    *,
    course_title: str,
    world_metaphor: str | None,
    node_title: str,
    node_summary: str,
    current_story: str,
    eval_prompts: list[dict[str, Any]],
    preferred_provider: str = "auto",
) -> tuple[str, str]:
    """Genera una explicacion conversada alternativa manteniendo el world_metaphor del ramo.

    Si no hay IA configurada, genera una analogia conversada determinista alternativa para no fallar offline.
    Devuelve (new_story_script, provider_used).
    """
    rubric_points = [
        pt
        for q in eval_prompts
        for pt in q.get("rubric_points", [])
    ]
    metaphor_hint = world_metaphor or f"Taller practico de {course_title}"

    try:
        system_prompt = (
            "Eres el narrador pedagogico de Brotal. Tu tarea es explicar un concepto universitario "
            "como una historia conversada continua en espanol, usando otra analogia o angulo fresco "
            "pero respetando la metafora de mundo del ramo. PROHIBIDO usar listas con bullets o markdown seco: "
            "solo 2 a 4 parrafos conversados naturales que cubran todos los conceptos clave de la rubrica."
        )
        user_prompt = (
            f"Ramo: {course_title}\n"
            f"Metafora del mundo: {metaphor_hint}\n"
            f"Nodo: {node_title} ({node_summary})\n"
            f"Conceptos que deben quedar claros en la narrativa: {', '.join(rubric_points)}\n"
            f"Historia anterior (usa otro enfoque/ejemplo distinto a este):\n{current_story}\n"
        )
        comp = complete_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            preferred_provider=preferred_provider,
            json_mode=False,
            temperature=0.65,
        )
        return (comp.text.strip(), comp.provider)
    except AiProviderError:
        # Fallback local conversado alternativo
        concepts_prose = ". Ademas, observa como ".join(rubric_points) if rubric_points else node_summary
        alt = (
            f"Miralo ahora desde otro angulo dentro de {metaphor_hint}. Cuando nos enfrentamos a {node_title}, "
            f"el error tipico es quedarse en la definicion de memoria en vez de seguir el flujo real del problema: "
            f"{node_summary}\n\n"
            f"Imagina que tienes que diagnosticarlo en vivo paso a paso: primero confirmas que {concepts_prose}. "
            f"Al conectar cada pieza por su funcion concreta en {metaphor_hint}, ya no necesitas memorizar listas "
            f"sueltas porque entiendes exactamente que pasa si una de las piezas falla."
        )
        return (alt, "local_fallback")
