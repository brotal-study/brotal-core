"""Pool multi-IA gratuito (Groq, Gemini Free, Ollama local) con rotacion y fallback (v1.0).

Soporta:
- Groq: llama-3.3-70b-versatile / fallback openai/gpt-oss-120b
- Gemini Free: gemini-2.5-flash (Google Generative Language REST API)
- Ollama local: http://127.0.0.1:11434 (o OLLAMA_URL configurado)
- Modo 'auto': prueba en orden los proveedores configurados y disponibles.
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
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
from app.services.evaluator import evaluate_rubric
from app.services.tts import split_story_sentences

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

LANGUAGE_INTERACTIVE_CHALLENGE_TYPES = (
    "word_order",
    "categorize",
    "find_error",
    "dictation",
)
LANGUAGE_CHALLENGE_TYPES = (
    "fill_blank",
    "translate",
    "speaking_prompt",
    *LANGUAGE_INTERACTIVE_CHALLENGE_TYPES,
)
ALL_VALID_CHALLENGE_TYPES = (
    "concept",
    "trace",
    "debug",
    "implement",
    *LANGUAGE_CHALLENGE_TYPES,
)

_L1_ES_DISTRACTOR_PAIRS: dict[str, str] = {
    "goes": "go",
    "go": "goes",
    "studies": "study",
    "study": "studies",
    "does": "do",
    "do": "does",
    "doesn't": "don't",
    "don't": "doesn't",
    "is": "are",
    "are": "is",
    "isn't": "aren't",
    "aren't": "isn't",
    "has": "have",
    "have": "has",
    "much": "many",
    "many": "much",
    "some": "any",
    "any": "some",
    "am": "is",
    "in": "on",
    "on": "in",
    "at": "in",
    "there": "their",
    "their": "there",
    "works": "work",
    "work": "works",
    "reviews": "review",
    "review": "reviews",
}

_FALLBACK_WORD_ORDER_POOL: tuple[dict[str, Any], ...] = (
    {
        "tiles": ["She", "goes", "to", "university", "every", "morning"],
        "distractors": ["go", "does"],
        "hint_es": "Present Simple en 3.ª persona singular (afirmativa); descarta los bloques de interferencia.",
    },
    {
        "tiles": ["Are", "there", "any", "notebooks", "on", "the", "desk?"],
        "distractors": ["Is", "some"],
        "hint_es": "Pregunta con sustantivo plural contable usando There are + any.",
    },
    {
        "tiles": ["He", "doesn't", "have", "much", "free", "time"],
        "distractors": ["has", "many"],
        "hint_es": "Negativa en 3.ª persona singular (doesn't + verbo base) con sustantivo incontable.",
    },
    {
        "tiles": ["How", "often", "do", "you", "study", "English?"],
        "distractors": ["does", "studies"],
        "hint_es": "Pregunta de frecuencia con sujeto 'you' y auxiliar correcto.",
    },
)

_FALLBACK_CATEGORIZE_POOL: tuple[dict[str, Any], ...] = (
    {
        "categories": ["Countable", "Uncountable"],
        "items": [
            "two notebooks",
            "many students",
            "some coffee",
            "much homework",
            "three classes",
            "a little time",
        ],
        "expected_map": {
            "two notebooks": "Countable",
            "many students": "Countable",
            "some coffee": "Uncountable",
            "much homework": "Uncountable",
            "three classes": "Countable",
            "a little time": "Uncountable",
        },
    },
    {
        "categories": ["There is", "There are"],
        "items": [
            "a whiteboard on the wall",
            "some milk in the fridge",
            "three computers in the lab",
            "many chairs in the room",
            "a quiet library nearby",
            "two exams this week",
        ],
        "expected_map": {
            "a whiteboard on the wall": "There is",
            "some milk in the fridge": "There is",
            "three computers in the lab": "There are",
            "many chairs in the room": "There are",
            "a quiet library nearby": "There is",
            "two exams this week": "There are",
        },
    },
    {
        "categories": ["Do / Don't", "Does / Doesn't"],
        "items": [
            "you study at night",
            "they live near campus",
            "she review vocabulary",
            "he have class on Friday",
            "we need more practice",
            "the bus arrive at eight",
        ],
        "expected_map": {
            "you study at night": "Do / Don't",
            "they live near campus": "Do / Don't",
            "she review vocabulary": "Does / Doesn't",
            "he have class on Friday": "Does / Doesn't",
            "we need more practice": "Do / Don't",
            "the bus arrive at eight": "Does / Doesn't",
        },
    },
    {
        "categories": ["Morning routine", "At university", "Evening habits"],
        "items": [
            "wake up at seven",
            "take a quick shower",
            "attend a grammar lecture",
            "take notes in class",
            "review vocabulary flashcards",
            "go to bed early",
        ],
        "expected_map": {
            "wake up at seven": "Morning routine",
            "take a quick shower": "Morning routine",
            "attend a grammar lecture": "At university",
            "take notes in class": "At university",
            "review vocabulary flashcards": "Evening habits",
            "go to bed early": "Evening habits",
        },
    },
)

_FALLBACK_FIND_ERROR_POOL: tuple[dict[str, Any], ...] = (
    {
        "sentence": "She don't study English at the library on Mondays.",
        "allow_no_error": True,
        "error_token": "don't",
        "correction": "doesn't",
    },
    {
        "sentence": "There is many students waiting outside the classroom today.",
        "allow_no_error": True,
        "error_token": "is",
        "correction": "are",
    },
    {
        "sentence": "He doesn't has enough time for breakfast before class.",
        "allow_no_error": True,
        "error_token": "has",
        "correction": "have",
    },
    {
        "sentence": "Is very important to practice speaking English every day.",
        "allow_no_error": True,
        "error_token": "Is",
        "correction": "It is",
    },
)

_FALLBACK_DICTATION_POOL: tuple[dict[str, Any], ...] = (
    {
        "audio_text": "She usually studies English at the library before her morning classes.",
        "accent": "us",
        "hint_es": "Escucha con atención la 3.ª persona singular y las preposiciones de lugar.",
    },
    {
        "audio_text": "There aren't any chairs left in the classroom, so we need two more.",
        "accent": "us",
        "hint_es": "Presta atención a la contracción negativa y al cuantificador plural.",
    },
    {
        "audio_text": "Does your classmate have enough time to review vocabulary this evening?",
        "accent": "gb",
        "hint_es": "Fíjate en el auxiliar al inicio de la pregunta y el verbo en forma base.",
    },
    {
        "audio_text": "I always drink some coffee and check my schedule at seven thirty.",
        "accent": "us",
        "hint_es": "Transcribe la oración completa cuidando adverbio de frecuencia y hora.",
    },
)


def _norm_en_tokens(text: str) -> list[str]:
    cleaned = (text or "").strip().lower()
    cleaned = cleaned.replace("\u2019", "'").replace("\u2018", "'").replace("`", "'")
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", cleaned)


def _infer_l1_es_distractors(tiles: list[str], existing: list[str]) -> list[str]:
    tiles_lower = {re.sub(r"[^a-z0-9']", "", t.lower()) for t in tiles}
    out: list[str] = []
    seen_lower: set[str] = set()
    for raw in existing:
        cleaned = str(raw).strip()
        low = re.sub(r"[^a-z0-9']", "", cleaned.lower())
        if cleaned and low not in seen_lower:
            out.append(cleaned)
            seen_lower.add(low)
        if len(out) >= 2:
            return out

    for tile in tiles:
        low = re.sub(r"[^a-z0-9']", "", tile.lower())
        cand = _L1_ES_DISTRACTOR_PAIRS.get(low)
        if cand and cand not in tiles_lower and cand not in seen_lower:
            out.append(cand)
            seen_lower.add(cand)
        if len(out) >= 2:
            return out

    for fallback_d in ("does", "do", "is", "are", "much", "many", "has", "have"):
        if fallback_d not in tiles_lower and fallback_d not in seen_lower:
            out.append(fallback_d)
            seen_lower.add(fallback_d)
        if len(out) >= 1:
            break

    return out[:2]


def normalize_language_interaction_data(
    challenge_type: str,
    raw_interaction_data: Any,
    *,
    question: str = "",
    node_title: str = "",
    idx: int = 0,
) -> dict[str, Any] | None:
    """Normalizador defensivo obligatorio para interaction_data en retos interactivos de language_studio.

    Garantiza un payload completo y valido para word_order, categorize, find_error y dictation
    incluso si el LLM devolvio None, {} o campos incompletos.
    """
    ct = (challenge_type or "").strip().lower()
    raw = raw_interaction_data if isinstance(raw_interaction_data, dict) else {}

    if ct == "word_order":
        fb = _FALLBACK_WORD_ORDER_POOL[idx % len(_FALLBACK_WORD_ORDER_POOL)]
        raw_tiles = raw.get("tiles")
        tiles = (
            [str(t).strip() for t in raw_tiles if str(t).strip()]
            if isinstance(raw_tiles, list)
            else []
        )
        used_fallback = False
        if len(tiles) < 4:
            cand_sentence = str(raw.get("sentence") or raw.get("target_sentence") or "").strip()
            if len(cand_sentence.split()) >= 4:
                tiles = cand_sentence.split()
            else:
                tiles = list(fb["tiles"])
                used_fallback = True

        raw_distractors = raw.get("distractors")
        existing_d = (
            [str(d).strip() for d in raw_distractors if str(d).strip()]
            if isinstance(raw_distractors, list)
            else []
        )
        if not existing_d and used_fallback:
            existing_d = list(fb["distractors"])
        distractors = _infer_l1_es_distractors(tiles, existing_d)

        hint_es = str(raw.get("hint_es") or "").strip()
        if not hint_es:
            hint_es = (
                str(fb["hint_es"])
                if used_fallback
                else f"Ordena los bloques en inglés aplicando {node_title or 'la regla del nodo'} y descarta distractores."
            )
        return {
            "tiles": tiles,
            "distractors": distractors,
            "hint_es": hint_es,
        }

    if ct == "categorize":
        fb = _FALLBACK_CATEGORIZE_POOL[idx % len(_FALLBACK_CATEGORIZE_POOL)]
        raw_cats = raw.get("categories")
        raw_items = raw.get("items")
        categories: list[str] = []
        if isinstance(raw_cats, list):
            for c in raw_cats:
                cs = str(c).strip()
                if cs and cs not in categories:
                    categories.append(cs)
        items: list[str] = []
        if isinstance(raw_items, list):
            for it in raw_items:
                its = str(it).strip()
                if its and its not in items:
                    items.append(its)

        raw_map = raw.get("expected_map")
        expected_map: dict[str, str] = {}
        if len(categories) >= 2 and len(items) >= 4:
            cat_lookup = {c.lower(): c for c in categories}
            if isinstance(raw_map, dict):
                for k, v in raw_map.items():
                    ks = str(k).strip()
                    vs = str(v).strip()
                    canon_cat = cat_lookup.get(vs.lower())
                    if ks and canon_cat:
                        if ks not in items:
                            items.append(ks)
                        expected_map[ks] = canon_cat
        else:
            categories = list(fb["categories"])
            items = list(fb["items"])
            expected_map = dict(fb["expected_map"])

        result: dict[str, Any] = {
            "categories": categories,
            "items": items,
        }
        if expected_map:
            result["expected_map"] = expected_map
        return result

    if ct == "find_error":
        fb = _FALLBACK_FIND_ERROR_POOL[idx % len(_FALLBACK_FIND_ERROR_POOL)]
        sentence = str(raw.get("sentence") or "").strip()
        used_fallback = False
        if len(sentence.split()) < 4:
            quoted = re.findall(r"['\"]([A-Za-z][^'\"]{10,160})['\"]", question or "")
            valid_quoted = next((q.strip() for q in quoted if len(q.strip().split()) >= 4), "")
            if valid_quoted:
                sentence = valid_quoted
            else:
                sentence = str(fb["sentence"])
                used_fallback = True

        raw_tokens = raw.get("tokens")
        tokens = (
            [str(t).strip() for t in raw_tokens if str(t).strip()]
            if isinstance(raw_tokens, list)
            else []
        )
        if len(tokens) < 4:
            tokens = [tok for tok in sentence.split() if tok]
        if len(tokens) < 4:
            sentence = str(fb["sentence"])
            tokens = sentence.split()
            used_fallback = True

        allow_no_error = (
            bool(raw["allow_no_error"])
            if isinstance(raw.get("allow_no_error"), bool)
            else True
        )
        raw_err_tok = raw.get("error_token")
        error_token = (
            str(raw_err_tok).strip() or None
            if raw_err_tok is not None
            else (fb["error_token"] if used_fallback else None)
        )
        raw_corr = raw.get("correction")
        correction = (
            str(raw_corr).strip() or None
            if raw_corr is not None
            else (fb["correction"] if used_fallback else None)
        )

        out_fe: dict[str, Any] = {
            "sentence": sentence,
            "tokens": tokens,
            "allow_no_error": allow_no_error,
        }
        if error_token is not None:
            out_fe["error_token"] = error_token
        if correction is not None:
            out_fe["correction"] = correction
        return out_fe

    if ct == "dictation":
        fb = _FALLBACK_DICTATION_POOL[idx % len(_FALLBACK_DICTATION_POOL)]
        audio_text = str(raw.get("audio_text") or "").strip()
        used_fallback = False
        if len(audio_text) < 4:
            audio_text = str(fb["audio_text"])
            used_fallback = True

        raw_accent = str(raw.get("accent") or (fb["accent"] if used_fallback else "us")).strip().lower()
        accent = raw_accent if raw_accent in ("us", "gb", "au") else "us"
        hint_es = str(raw.get("hint_es") or "").strip()
        if not hint_es:
            hint_es = (
                str(fb["hint_es"])
                if used_fallback
                else "Escucha el audio en inglés y escribe exactamente lo que oyes."
            )
        return {
            "audio_text": audio_text,
            "accent": accent,
            "hint_es": hint_es,
        }

    return raw if raw else None


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
    max_tokens: int | None = None,
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
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
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
    max_tokens: int | None = None,
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
    if max_tokens is not None:
        gen_config["maxOutputTokens"] = max_tokens
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
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> AiCompletion:
    """Ejecuta una completacion rotando entre los proveedores gratuitos disponibles."""
    status = configured_providers()
    order = _provider_order(preferred_provider, status)
    if not order:
        raise AiProviderError("No hay proveedores IA configurados (configura Groq, Gemini u Ollama)")

    extra_kw: dict[str, Any] = {}
    if max_tokens is not None:
        extra_kw["max_tokens"] = max_tokens
    if timeout is not None:
        extra_kw["timeout"] = timeout

    errors: list[str] = []
    for provider in order:
        try:
            if provider == "groq":
                return call_groq(messages, json_mode=json_mode, temperature=temperature, **extra_kw)
            if provider == "gemini":
                return call_gemini(messages, json_mode=json_mode, temperature=temperature, **extra_kw)
            if provider == "ollama":
                ollama_kw = {"timeout": timeout} if timeout is not None else {}
                return call_ollama(messages, json_mode=json_mode, temperature=temperature, **ollama_kw)
        except (AiProviderError, httpx.HTTPError, ValueError, TypeError) as exc:
            errors.append(f"{provider}: {exc}")
            continue

    raise AiProviderError("Todos los proveedores IA fallaron: " + " | ".join(errors))


def _is_placeholder_starter(code: str | None) -> bool:
    if not code:
        return True
    s = code.strip()
    if not s:
        return True
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    return len(lines) == 1 and (
        lines[0].startswith(("//", "--", "#"))
        or (lines[0].startswith("/*") and lines[0].endswith("*/"))
    )


def _expand_single_line_brace_code(raw_code: str) -> str:
    """Formatea codigo Java/C de una sola linea con llaves y punto y coma en multiples lineas indentadas."""
    indent = 0
    out_lines: list[str] = []
    buf: list[str] = []
    paren_depth = 0
    in_str: str | None = None
    escape = False
    i = 0
    n = len(raw_code)

    def flush_line() -> None:
        line = re.sub(r"[ \t]+", " ", "".join(buf)).strip()
        buf.clear()
        if line:
            out_lines.append(("    " * indent) + line)

    while i < n:
        ch = raw_code[i]
        if in_str is not None:
            buf.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
            i += 1
            continue

        if ch in ('"', "'"):
            in_str = ch
            buf.append(ch)
            i += 1
            continue

        if ch == "/" and i + 1 < n and raw_code[i + 1] == "*":
            end_comment = raw_code.find("*/", i + 2)
            if end_comment == -1:
                buf.append(raw_code[i:])
                break
            comment_block = raw_code[i : end_comment + 2]
            if "".join(buf).strip():
                flush_line()
            buf.append(comment_block)
            flush_line()
            i = end_comment + 2
            continue

        if ch == "/" and i + 1 < n and raw_code[i + 1] == "/":
            end_ln = raw_code.find("\n", i + 2)
            if "".join(buf).strip():
                flush_line()
            if end_ln == -1:
                buf.append(raw_code[i:])
                flush_line()
                break
            buf.append(raw_code[i:end_ln])
            flush_line()
            i = end_ln + 1
            continue

        if ch == "(":
            paren_depth += 1
            buf.append(ch)
        elif ch == ")":
            paren_depth = max(0, paren_depth - 1)
            buf.append(ch)
        elif ch == "{" and paren_depth == 0:
            cur = "".join(buf).rstrip()
            buf.clear()
            if cur:
                buf.append(cur + " {")
            else:
                buf.append("{")
            flush_line()
            indent += 1
        elif ch == "}" and paren_depth == 0:
            flush_line()
            indent = max(0, indent - 1)
            j = i + 1
            while j < n and raw_code[j] in " \t":
                j += 1
            if j < n and raw_code[j] == ";":
                out_lines.append(("    " * indent) + "};")
                i = j + 1
                continue
            out_lines.append(("    " * indent) + "}")
        elif ch == ";" and paren_depth == 0:
            buf.append(";")
            flush_line()
        elif ch == "\n":
            flush_line()
        else:
            buf.append(ch)
        i += 1

    flush_line()
    return "\n".join(out_lines)


def format_multiline_starter_code(starter_code: str | None, language: str = "java") -> str | None:
    """Garantiza que starter_code con codigo real nunca quede aplastado en una sola linea."""
    if starter_code is None:
        return None
    cleaned = starter_code.strip()
    if not cleaned or _is_placeholder_starter(cleaned):
        return cleaned

    lang = (language or "java").strip().lower()
    raw_lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    non_comment_lines = [
        ln
        for ln in raw_lines
        if not ln.strip().startswith(("//", "--", "#"))
        and not (ln.strip().startswith("/*") and ln.strip().endswith("*/"))
    ]

    if lang == "sql" or (
        "{" not in cleaned
        and re.search(r"\bSELECT\b[\s\S]+\bFROM\b", cleaned, re.IGNORECASE)
    ):
        if len(non_comment_lines) <= 1:
            formatted_sql = re.sub(
                r"\s+\b((?:INNER|LEFT|RIGHT|FULL)\s+JOIN|JOIN|FROM|WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT|VALUES|SET)\b",
                r"\n\1",
                cleaned,
                flags=re.IGNORECASE,
            )
            return formatted_sql.strip()
        return cleaned

    needs_brace_expand = len(non_comment_lines) <= 1 and ("{" in cleaned or cleaned.count(";") >= 2)
    if not needs_brace_expand and len(non_comment_lines) <= 2:
        for ln in non_comment_lines:
            if "{" in ln and "}" in ln and ";" in ln:
                needs_brace_expand = True
                break

    if needs_brace_expand:
        return _expand_single_line_brace_code(cleaned)

    return cleaned


def _strip_code_comments(code: str) -> str:
    no_block = re.sub(r"/\*[\s\S]*?\*/", " ", code)
    lines = []
    for ln in no_block.splitlines():
        s = ln.strip()
        if s.startswith(("//", "--", "#")):
            continue
        s = re.sub(r"//.*$", "", s).strip()
        if s:
            lines.append(s)
    return "\n".join(lines)


def sanitize_code_prompt(
    question: str,
    starter_code: str | None,
    language: str = "java",
) -> tuple[str, str | None]:
    """Formatea starter_code multilinea y elimina codigo duplicado embebido en question."""
    q_orig = (question or "").strip()
    if starter_code is None:
        return (q_orig, None)

    raw_starter = starter_code.strip()
    formatted_starter = format_multiline_starter_code(raw_starter, language)
    if not raw_starter or _is_placeholder_starter(raw_starter):
        return (q_orig, formatted_starter)

    q_clean = re.sub(r"```[\s\S]*?```", " ", q_orig)

    candidates = [raw_starter]
    if formatted_starter and formatted_starter != raw_starter:
        candidates.append(formatted_starter)
    stripped_comments = _strip_code_comments(raw_starter)
    if stripped_comments and stripped_comments not in candidates:
        candidates.append(stripped_comments)

    for cand in candidates:
        tokens = [t for t in re.split(r"\s+", cand.strip()) if t]
        if len(tokens) >= 3:
            pat = r"[:\s]*`?" + r"\s+".join(re.escape(t) for t in tokens) + r"`?"
            q_clean = re.sub(pat, " ", q_clean, flags=re.IGNORECASE)

    # Recortar bloque de codigo duplicado al final tras ':' o salto de linea
    q_clean = re.sub(
        r"[:\n]\s*`?(?:import\s+[\w.]+;\s*)*(?:(?:public|private|protected|static|final|abstract)\s+)*"
        r"(?:class|interface|void|int|double|float|long|boolean|String|List|Map|Set)\b[\s\S]*\{[\s\S]*\}[\s;]*`?\s*$",
        ".",
        q_clean,
    )
    q_clean = re.sub(
        r"[:\n]\s*`?SELECT\s+[\s\S]+\s+FROM\s+[\s\S]+;?\s*`?\s*$",
        ".",
        q_clean,
        flags=re.IGNORECASE,
    )
    q_clean = re.sub(
        r"[:\n]\s*`?def\s+[A-Za-z_]\w*\s*\([^)]*\)\s*(?:->\s*[^:]+)?:\s+[\s\S]+`?\s*$",
        ".",
        q_clean,
    )

    q_clean = re.sub(r"[ \t]+", " ", q_clean)
    q_clean = re.sub(r"\n{2,}", "\n", q_clean).strip()
    q_clean = re.sub(r"\s*:\s*$", ".", q_clean)
    q_clean = re.sub(r"\.{2,}$", ".", q_clean).strip()

    if len(q_clean) < 10:
        q_clean = "Analiza el código del editor, identifica el problema técnico y resuélvelo según los criterios del nodo."

    return (q_clean, formatted_starter)


def _clean_fenced_solution(raw_sol: Any) -> str | None:
    if not isinstance(raw_sol, str):
        return None
    s = raw_sol.strip()
    if not s:
        return None
    m = re.match(r"^```[a-zA-Z0-9_+-]*[ \t]*\n([\s\S]*?)\n?```$", s)
    if m:
        return m.group(1).strip() or None
    return s


def _format_expected_categorize_solution(interaction_data: dict[str, Any]) -> str | None:
    expected_map = interaction_data.get("expected_map")
    categories = interaction_data.get("categories") or []
    if not isinstance(expected_map, dict) or not expected_map:
        return None
    grouped: dict[str, list[str]] = {str(c): [] for c in categories if str(c).strip()}
    for item, cat in expected_map.items():
        cs = str(cat).strip()
        its = str(item).strip()
        if cs and its:
            grouped.setdefault(cs, []).append(its)
    lines = [f"{cat}: {', '.join(its)}" for cat, its in grouped.items() if its]
    return "\n".join(lines) if lines else None


def _build_fixed_find_error_sentence(interaction_data: dict[str, Any]) -> str:
    sentence = str(interaction_data.get("sentence") or "").strip()
    error_token = str(interaction_data.get("error_token") or "").strip()
    correction = str(interaction_data.get("correction") or "").strip()
    if sentence and error_token and correction:
        pattern = re.compile(re.escape(error_token), re.IGNORECASE)
        replaced, count = pattern.subn(correction, sentence, count=1)
        if count > 0:
            return replaced
    return sentence


def _interactive_reference_solution(ct: str, interaction_data: dict[str, Any] | None) -> str | None:
    if not isinstance(interaction_data, dict):
        return None
    if ct == "word_order":
        tiles = [str(t).strip() for t in (interaction_data.get("tiles") or []) if str(t).strip()]
        return " ".join(tiles) if tiles else None
    if ct == "categorize":
        return _format_expected_categorize_solution(interaction_data)
    if ct == "find_error":
        error_token = interaction_data.get("error_token")
        correction = interaction_data.get("correction")
        fixed_sentence = _build_fixed_find_error_sentence(interaction_data)
        if error_token and correction:
            return f"{fixed_sentence} (Error: {error_token} -> Corrección: {correction})"
        return fixed_sentence or "Sin error"
    if ct == "dictation":
        audio_text = str(interaction_data.get("audio_text") or "").strip()
        return audio_text or None
    return None


def _parse_categorize_answer(student_ans: str, categories: list[str]) -> dict[str, str]:
    """Parsea líneas 'Categoria: item1, item2' en un mapa item_lower -> categoria_canonica."""
    cat_lookup = {c.strip().lower(): c.strip() for c in categories if c.strip()}
    assigned: dict[str, str] = {}
    raw_lines = [ln.strip() for ln in re.split(r"[\n;]+", student_ans or "") if ln.strip()]
    for ln in raw_lines:
        if ":" not in ln:
            continue
        cat_raw, items_raw = ln.split(":", 1)
        cat_clean = cat_raw.strip().lower()
        matched_cat = cat_lookup.get(cat_clean)
        if not matched_cat:
            for k_low, k_canon in cat_lookup.items():
                if k_low in cat_clean or cat_clean in k_low:
                    matched_cat = k_canon
                    break
        if not matched_cat:
            continue
        for part in items_raw.split(","):
            item_clean = part.strip()
            if item_clean:
                assigned[item_clean.lower()] = matched_cat
    return assigned


def _evaluate_single_interactive_prompt(
    q: dict[str, Any],
    student_ans: str,
    idx: int,
) -> dict[str, Any]:
    """Evalua deterministicamente un reto interactivo de language_studio (word_order/categorize/find_error/dictation)."""
    qid = str(q.get("id") or f"q{idx + 1}")
    ct = str(q.get("challenge_type") or "concept").strip().lower()
    r_points = [str(p) for p in (q.get("rubric_points") or [])]
    q_keys = [f"{qid}::{i}" for i in range(len(r_points))]
    idata = normalize_language_interaction_data(
        ct,
        q.get("interaction_data"),
        question=str(q.get("question") or ""),
        idx=idx,
    ) or {}
    ans = (student_ans or "").strip()

    ratio = 0.0
    status = "failed"
    diagnosis = ""
    code_fixes: list[dict[str, str]] = []
    corrected_solution: str | None = None
    imprecision: str | None = None

    if ct == "word_order":
        tiles = [str(t).strip() for t in (idata.get("tiles") or []) if str(t).strip()]
        distractors = [str(d).strip() for d in (idata.get("distractors") or []) if str(d).strip()]
        expected_sentence = " ".join(tiles)
        exp_tokens = _norm_en_tokens(expected_sentence)
        stu_tokens = _norm_en_tokens(ans)
        used_distractors = [
            d
            for d in distractors
            if _norm_en_tokens(d)
            and all(tok in stu_tokens for tok in _norm_en_tokens(d))
            and not all(tok in exp_tokens for tok in _norm_en_tokens(d))
        ]
        if stu_tokens and stu_tokens == exp_tokens:
            ratio = 1.0
            status = "passed"
            diagnosis = "Excelente: armaste la oración en el orden natural en inglés descartando los distractores."
        elif not stu_tokens:
            ratio = 0.0
            status = "failed"
            diagnosis = "No armaste ninguna oración en inglés."
            imprecision = f"Falta construir la oración objetivo: '{expected_sentence}'."
            corrected_solution = expected_sentence
            code_fixes.append(
                {
                    "broken_snippet": "(sin oración armada)",
                    "fixed_snippet": expected_sentence,
                    "why": "Este cambio muestra el orden natural Sujeto + Verbo + Complemento en inglés.",
                }
            )
        else:
            sim = difflib.SequenceMatcher(None, exp_tokens, stu_tokens).ratio()
            if used_distractors:
                sim = max(0.0, sim - 0.25)
            ratio = round(sim, 2)
            if ratio >= 0.95 and not used_distractors:
                status = "passed"
                diagnosis = "Oración correcta en inglés respetando orden y concordancia."
            elif ratio >= 0.55:
                status = "partial"
                if used_distractors:
                    diagnosis = (
                        f"Estructura casi lograda, pero incluiste el distractor de interferencia "
                        f"'{', '.join(used_distractors)}'."
                    )
                    imprecision = f"Incluiste un distractor ({', '.join(used_distractors)}) en lugar de la forma natural en inglés."
                else:
                    diagnosis = "Tienes varias palabras correctas, pero el orden de los bloques en inglés no coincide."
                    imprecision = f"Revisa el orden sintáctico de la oración: '{expected_sentence}'."
                corrected_solution = expected_sentence
                code_fixes.append(
                    {
                        "broken_snippet": ans[:180],
                        "fixed_snippet": expected_sentence,
                        "why": (
                            f"Este cambio corrige la interferencia español-inglés eliminando '{', '.join(used_distractors)}' "
                            "y restaurando el orden natural."
                            if used_distractors
                            else "Este cambio corrige el orden sintáctico natural en inglés."
                        ),
                    }
                )
            else:
                status = "failed"
                diagnosis = "El orden de las palabras o la elección de bloques no forma una oración gramatical válida."
                imprecision = f"La oración esperada era '{expected_sentence}'."
                corrected_solution = expected_sentence
                code_fixes.append(
                    {
                        "broken_snippet": ans[:180],
                        "fixed_snippet": expected_sentence,
                        "why": "Este cambio corrige el orden Sujeto + Verbo + Complemento y descarta distractores.",
                    }
                )

    elif ct == "categorize":
        categories = [str(c).strip() for c in (idata.get("categories") or []) if str(c).strip()]
        items = [str(it).strip() for it in (idata.get("items") or []) if str(it).strip()]
        expected_map = idata.get("expected_map") if isinstance(idata.get("expected_map"), dict) else {}
        assigned = _parse_categorize_answer(ans, categories)
        ref_sol = _format_expected_categorize_solution(idata)

        if expected_map:
            total = len(expected_map)
            correct = 0
            wrong_items: list[tuple[str, str | None, str]] = []
            for item_key, exp_cat in expected_map.items():
                stu_cat = assigned.get(item_key.strip().lower())
                if stu_cat and stu_cat.lower() == str(exp_cat).strip().lower():
                    correct += 1
                else:
                    wrong_items.append((item_key, stu_cat, str(exp_cat)))
            ratio = correct / total if total else 0.0
            if ratio >= 0.99:
                status = "passed"
                diagnosis = "Clasificación perfecta: asignaste todos los bloques a su categoría correcta."
            elif ratio >= 0.5:
                status = "partial"
                diagnosis = (
                    f"Clasificaste correctamente {correct} de {total} bloques, "
                    "pero hay asignaciones que debes ajustar."
                )
                imprecision = f"Revisa la clasificación de: {', '.join(w[0] for w in wrong_items[:3])}."
                corrected_solution = ref_sol
                for w_item, stu_cat, exp_cat in wrong_items[:3]:
                    code_fixes.append(
                        {
                            "broken_snippet": f"{stu_cat}: {w_item}" if stu_cat else f"(sin clasificar): {w_item}",
                            "fixed_snippet": f"{exp_cat}: {w_item}",
                            "why": f"Este cambio corrige la categoría: '{w_item}' corresponde a '{exp_cat}'.",
                        }
                    )
            else:
                status = "failed"
                diagnosis = (
                    f"Solo acertaste {correct} de {total} bloques. Revisa el criterio funcional de cada categoría."
                )
                imprecision = f"Clasificación incompleta o errónea en {len(wrong_items)} bloques."
                corrected_solution = ref_sol
                for w_item, stu_cat, exp_cat in wrong_items[:3]:
                    code_fixes.append(
                        {
                            "broken_snippet": f"{stu_cat}: {w_item}" if stu_cat else f"(sin clasificar): {w_item}",
                            "fixed_snippet": f"{exp_cat}: {w_item}",
                            "why": f"Este cambio corrige la categoría: '{w_item}' corresponde a '{exp_cat}'.",
                        }
                    )
        else:
            total = len(items)
            matched = sum(1 for it in items if it.lower() in assigned)
            ratio = matched / total if total else 0.0
            if ratio >= 0.99:
                status = "passed"
                diagnosis = "Clasificaste todos los bloques en las categorías solicitadas."
            elif ratio >= 0.5:
                status = "partial"
                diagnosis = f"Asignaste {matched} de {total} bloques; falta clasificar los restantes."
                imprecision = "Faltaron bloques por asignar a sus categorías."
            else:
                status = "failed"
                diagnosis = "No clasificaste suficientes bloques con el formato 'Categoría: item1, item2'."
                imprecision = "Completa la clasificación usando cada categoría disponible."

    elif ct == "find_error":
        sentence = str(idata.get("sentence") or "").strip()
        error_token = str(idata.get("error_token") or "").strip() or None
        correction = str(idata.get("correction") or "").strip() or None
        allow_no_error = bool(idata.get("allow_no_error", True))
        fixed_sentence = _build_fixed_find_error_sentence(idata)

        ans_low = ans.lower()
        said_no_error = bool(re.match(r"^(?:sin\s+error|no\s+error|no\s+hay\s+error|correcta?)\.?$", ans_low))
        parsed_match = re.search(
            r"error\s*:\s*(.+?)\s*(?:->|→)\s*correcci[oó]n\s*:\s*(.+)$",
            ans,
            flags=re.IGNORECASE,
        )

        if error_token is None and allow_no_error:
            if said_no_error:
                ratio = 1.0
                status = "passed"
                diagnosis = "Correcto: identificaste que la oración en inglés no tiene errores gramaticales."
            else:
                ratio = 0.0
                status = "failed"
                diagnosis = "La oración original ya era correcta en inglés; debías marcar 'Sin error'."
                imprecision = "Se marcó un error inexistente en una oración gramaticalmente válida."
                corrected_solution = f"Sin error ({sentence})"
                code_fixes.append(
                    {
                        "broken_snippet": ans[:180] or "(sin respuesta)",
                        "fixed_snippet": "Sin error",
                        "why": "Este cambio corrige el diagnóstico porque la oración original cumple las reglas del inglés.",
                    }
                )
        else:
            exp_err_toks = _norm_en_tokens(error_token or "")
            exp_corr_toks = _norm_en_tokens(correction or "")
            exp_fixed_toks = _norm_en_tokens(fixed_sentence)
            if not ans or said_no_error:
                ratio = 0.0
                status = "failed"
                diagnosis = (
                    f"La oración sí contenía un error en '{error_token}'. "
                    f"La forma natural en inglés usa '{correction}'."
                )
                imprecision = f"No se detectó el error '{error_token}' -> '{correction}'."
                corrected_solution = f"{fixed_sentence} (Error: {error_token} -> Corrección: {correction})"
                code_fixes.append(
                    {
                        "broken_snippet": ans or sentence,
                        "fixed_snippet": f"Error: {error_token} -> Corrección: {correction}",
                        "why": f"Este cambio corrige '{error_token}' por '{correction}' evitando interferencia del español.",
                    }
                )
            elif parsed_match:
                picked_tok = parsed_match.group(1).strip()
                picked_corr = parsed_match.group(2).strip()
                tok_ok = _norm_en_tokens(picked_tok) == exp_err_toks
                corr_ok = bool(exp_corr_toks) and (
                    _norm_en_tokens(picked_corr) == exp_corr_toks
                    or _norm_en_tokens(picked_corr) == exp_fixed_toks
                )
                if tok_ok and corr_ok:
                    ratio = 1.0
                    status = "passed"
                    diagnosis = f"Excelente detección: identificaste '{error_token}' y lo corregiste por '{correction}'."
                elif tok_ok:
                    ratio = 0.5
                    status = "partial"
                    diagnosis = (
                        f"Identificaste bien la palabra con error ('{error_token}'), "
                        f"pero la corrección natural es '{correction}'."
                    )
                    imprecision = f"Corrige '{error_token}' por '{correction}'."
                    corrected_solution = f"{fixed_sentence} (Error: {error_token} -> Corrección: {correction})"
                    code_fixes.append(
                        {
                            "broken_snippet": ans[:180],
                            "fixed_snippet": f"Error: {error_token} -> Corrección: {correction}",
                            "why": f"Este cambio corrige la forma sugerida usando '{correction}' en inglés natural.",
                        }
                    )
                elif corr_ok:
                    ratio = 0.6
                    status = "partial"
                    diagnosis = f"La corrección '{correction}' es adecuada, pero el token erróneo exacto era '{error_token}'."
                    imprecision = f"El token con error exacto en la oración es '{error_token}'."
                    corrected_solution = f"{fixed_sentence} (Error: {error_token} -> Corrección: {correction})"
                    code_fixes.append(
                        {
                            "broken_snippet": ans[:180],
                            "fixed_snippet": f"Error: {error_token} -> Corrección: {correction}",
                            "why": f"Este cambio señala exactamente el token erróneo '{error_token}' y su corrección '{correction}'.",
                        }
                    )
                else:
                    ratio = 0.0
                    status = "failed"
                    diagnosis = (
                        f"El error real de la oración está en '{error_token}' y debe corregirse por '{correction}'."
                    )
                    imprecision = f"El error en la oración era '{error_token}' -> '{correction}'."
                    corrected_solution = f"{fixed_sentence} (Error: {error_token} -> Corrección: {correction})"
                    code_fixes.append(
                        {
                            "broken_snippet": ans[:180],
                            "fixed_snippet": f"Error: {error_token} -> Corrección: {correction}",
                            "why": f"Este cambio corrige '{error_token}' por '{correction}' según la gramática del inglés.",
                        }
                    )
            else:
                if _norm_en_tokens(ans) == exp_fixed_toks:
                    ratio = 1.0
                    status = "passed"
                    diagnosis = "Corregiste correctamente la oración completa en inglés."
                else:
                    ratio = 0.0
                    status = "failed"
                    diagnosis = f"No identificaste correctamente el error '{error_token}' -> '{correction}'."
                    imprecision = f"Revisa el error '{error_token}' en la oración original."
                    corrected_solution = f"{fixed_sentence} (Error: {error_token} -> Corrección: {correction})"
                    code_fixes.append(
                        {
                            "broken_snippet": ans[:180],
                            "fixed_snippet": f"Error: {error_token} -> Corrección: {correction}",
                            "why": f"Este cambio corrige '{error_token}' por '{correction}' en la oración.",
                        }
                    )

    elif ct == "dictation":
        audio_text = str(idata.get("audio_text") or "").strip()
        exp_tokens = _norm_en_tokens(audio_text)
        stu_tokens = _norm_en_tokens(ans)
        if stu_tokens and stu_tokens == exp_tokens:
            ratio = 1.0
            status = "passed"
            diagnosis = "Transcripción exacta: captaste correctamente todas las palabras del audio en inglés."
        elif not stu_tokens:
            ratio = 0.0
            status = "failed"
            diagnosis = "No escribiste ninguna transcripción del audio."
            imprecision = f"Falta transcribir la frase del audio: '{audio_text}'."
            corrected_solution = audio_text
            code_fixes.append(
                {
                    "broken_snippet": "(sin transcripción)",
                    "fixed_snippet": audio_text,
                    "why": "Este cambio muestra la transcripción exacta de la frase escuchada en inglés.",
                }
            )
        else:
            sim = difflib.SequenceMatcher(None, exp_tokens, stu_tokens).ratio()
            ratio = round(sim, 2)
            if ratio >= 0.92:
                ratio = 1.0
                status = "passed"
                diagnosis = "Muy buena transcripción: coincide casi exactamente con el audio en inglés."
            elif ratio >= 0.65:
                status = "partial"
                diagnosis = "Transcripción parcial: captaste la idea general pero faltaron o cambiaron algunas palabras."
                imprecision = f"Compara tu transcripción palabra por palabra contra: '{audio_text}'."
                corrected_solution = audio_text
                code_fixes.append(
                    {
                        "broken_snippet": ans[:180],
                        "fixed_snippet": audio_text,
                        "why": "Este cambio corrige las palabras omitidas o mal escritas respecto al audio original.",
                    }
                )
            else:
                status = "failed"
                diagnosis = "La transcripción difiere demasiado del audio original en inglés."
                imprecision = f"Escucha nuevamente con atención y compáralo con: '{audio_text}'."
                corrected_solution = audio_text
                code_fixes.append(
                    {
                        "broken_snippet": ans[:180],
                        "fixed_snippet": audio_text,
                        "why": "Este cambio muestra la frase exacta del dictado para afinar comprensión auditiva y ortografía.",
                    }
                )

    n_pts = len(q_keys)
    if n_pts == 0:
        covered_keys: list[str] = []
    elif status == "passed" or ratio >= 0.92:
        covered_keys = list(q_keys)
    elif ratio >= 0.5:
        covered_count = max(1, min(n_pts - 1, round(n_pts * ratio))) if n_pts > 1 else 0
        covered_keys = q_keys[:covered_count]
    else:
        covered_keys = []

    return {
        "prompt_id": qid,
        "ratio": ratio,
        "covered_keys": covered_keys,
        "imprecision": imprecision,
        "review": {
            "prompt_id": qid,
            "status": status,
            "diagnosis": diagnosis,
            "code_fixes": code_fixes,
            "corrected_solution": corrected_solution,
        },
    }


def evaluate_language_fallback_deterministic(
    *,
    node_title: str,
    eval_prompts: list[dict[str, Any]],
    answers_by_prompt: dict[str, str],
) -> dict[str, Any]:
    """Evaluador offline determinista para language_studio (incluye word_order, categorize, find_error y dictation)."""
    covered_points: list[str] = []
    imprecisions: list[str] = []
    raw_reviews: list[dict[str, Any]] = []
    prompt_ratios: list[float] = []

    for idx, q in enumerate(eval_prompts):
        qid = str(q.get("id") or f"q{idx + 1}")
        ct = str(q.get("challenge_type") or "concept").strip().lower()
        ans = (answers_by_prompt.get(qid) or "").strip()

        if ct in LANGUAGE_INTERACTIVE_CHALLENGE_TYPES:
            res = _evaluate_single_interactive_prompt(q, ans, idx)
            covered_points.extend(res["covered_keys"])
            prompt_ratios.append(float(res["ratio"]))
            if res["imprecision"]:
                imprecisions.append(str(res["imprecision"]))
            raw_reviews.append(res["review"])
        else:
            # Fallback para fill_blank, translate, speaking_prompt o concept en el mismo nodo
            fb_items = evaluate_rubric([q], answers_by_prompt, None)
            en_tokens = _norm_en_tokens(ans)
            q_keys = [f"{qid}::{i}" for i in range(len(q.get("rubric_points") or []))]
            matched_keys = [f"{it['prompt_id']}::{it['point_index']}" for it in fb_items if it["covered"]]
            if not matched_keys and ans and ct in ("fill_blank", "translate", "speaking_prompt"):
                min_words = 6 if ct == "speaking_prompt" else (3 if ct == "translate" else 1)
                if len(en_tokens) >= min_words:
                    matched_keys = q_keys[: max(1, len(q_keys) // 2)]
            covered_points.extend(matched_keys)
            p_ratio = len(matched_keys) / len(q_keys) if q_keys else (1.0 if ans else 0.0)
            prompt_ratios.append(p_ratio)
            if p_ratio < 1.0:
                missed = [
                    str(q.get("rubric_points", [])[i])
                    for i, k in enumerate(q_keys)
                    if k not in matched_keys
                ]
                if missed:
                    imprecisions.append(f"En {qid}: refuerza {missed[0]}.")

    avg_ratio = sum(prompt_ratios) / len(prompt_ratios) if prompt_ratios else 0.0
    score = round(max(1.0, min(10.0, 1.0 + 9.0 * avg_ratio)), 1)
    if avg_ratio >= 0.99 and not imprecisions:
        score = 10.0

    re_explanation: str | None = None
    if score < 7.0:
        if imprecisions:
            re_explanation = (
                "Repasemos los puntos clave en inglés antes del próximo intento: "
                + " ".join(imprecisions[:3])
            )
        else:
            re_explanation = (
                f"Repasa la explicación de {node_title} cuidando el orden Sujeto + Verbo + Complemento, "
                "los auxiliares do/does y la concordancia."
            )

    prompt_reviews, routing_suggestion = build_prompt_reviews_and_routing(
        node_title=node_title,
        eval_prompts=eval_prompts,
        answers_by_prompt=answers_by_prompt,
        covered_points=covered_points,
        score=score,
        imprecisions=imprecisions,
        raw_prompt_reviews=raw_reviews,
        raw_routing_suggestion=None,
    )

    return {
        "score": score,
        "covered_points": covered_points,
        "imprecisions": imprecisions,
        "re_explanation": re_explanation,
        "prompt_reviews": prompt_reviews,
        "routing_suggestion": routing_suggestion,
        "provider": "local_fallback",
        "model": "local-fallback",
    }


def build_prompt_reviews_and_routing(
    *,
    node_title: str,
    eval_prompts: list[dict[str, Any]],
    answers_by_prompt: dict[str, str],
    covered_points: list[str],
    score: float,
    imprecisions: list[str] | None = None,
    raw_prompt_reviews: Any = None,
    raw_routing_suggestion: Any = None,
) -> tuple[list[dict[str, Any]], str]:
    """Valida/sanitiza prompt_reviews y routing_suggestion o construye un fallback determinista limpio."""
    covered_set = set(covered_points)
    imp_list = [str(x).strip() for x in (imprecisions or []) if str(x).strip()]

    raw_by_id: dict[str, dict[str, Any]] = {}
    raw_list: list[dict[str, Any]] = []
    if isinstance(raw_prompt_reviews, list):
        for item in raw_prompt_reviews:
            if isinstance(item, dict):
                raw_list.append(item)
                pid = str(item.get("prompt_id") or item.get("id") or "").strip()
                if pid:
                    raw_by_id[pid] = item

    reviews_out: list[dict[str, Any]] = []
    for idx, q in enumerate(eval_prompts):
        qid = str(q.get("id") or f"q{idx + 1}")
        ct = str(q.get("challenge_type") or "concept").strip().lower()
        lang = str(q.get("language") or "java").strip().lower()
        starter = str(q.get("starter_code") or "").strip()
        interaction_data = q.get("interaction_data") if isinstance(q.get("interaction_data"), dict) else None
        student_ans = (answers_by_prompt.get(qid) or "").strip()
        r_points = [str(p) for p in (q.get("rubric_points") or [])]
        q_keys = [f"{qid}::{i}" for i in range(len(r_points))]

        covered_count = sum(1 for k in q_keys if k in covered_set)
        missed_criteria = [r_points[i] for i, k in enumerate(q_keys) if k not in covered_set]
        covered_criteria = [r_points[i] for i, k in enumerate(q_keys) if k in covered_set]

        if q_keys:
            if covered_count == len(q_keys):
                derived_status = "passed"
            elif covered_count == 0:
                derived_status = "failed"
            else:
                derived_status = "partial"
        else:
            derived_status = "passed" if score >= 7.0 else "failed"

        raw_item = raw_by_id.get(qid)
        if raw_item is None and idx < len(raw_list):
            candidate_item = raw_list[idx]
            cand_pid = str(candidate_item.get("prompt_id") or candidate_item.get("id") or "").strip()
            if not cand_pid or cand_pid not in {str(p.get("id")) for p in eval_prompts}:
                raw_item = candidate_item
        raw_item = raw_item or {}

        code_fixes: list[dict[str, str]] = []
        raw_fixes = raw_item.get("code_fixes")
        if isinstance(raw_fixes, list):
            for cf in raw_fixes[:6]:
                if isinstance(cf, dict):
                    broken = str(cf.get("broken_snippet") or "").strip()
                    fixed = str(cf.get("fixed_snippet") or "").strip()
                    why = str(cf.get("why") or "").strip()
                    if (broken or fixed) and why:
                        code_fixes.append(
                            {
                                "broken_snippet": broken or "(código incompleto u omitido)",
                                "fixed_snippet": fixed or "(aplicar corrección)",
                                "why": why,
                            }
                        )

        raw_status = str(raw_item.get("status") or "").strip().lower()
        if raw_status in ("passed", "partial", "failed"):
            status = raw_status
        else:
            status = derived_status

        if score == 10.0 and covered_count == len(q_keys) and not code_fixes and not imp_list:
            status = "passed"
        elif status == "passed" and (code_fixes or covered_count < len(q_keys)):
            status = "partial" if covered_count > 0 or code_fixes else "failed"

        ref_interactive_sol = _interactive_reference_solution(ct, interaction_data)

        # Si es reto de codigo o idioma no aprobado y no vinieron code_fixes del proveedor, generar guia puntual
        if ct in ("debug", "implement", "trace") and status != "passed" and not code_fixes:
            formatted_starter = format_multiline_starter_code(starter, lang) or starter
            code_lines = [
                ln.strip()
                for ln in (student_ans or formatted_starter).splitlines()
                if ln.strip() and not ln.strip().startswith("//") and not ln.strip().startswith("--")
            ]
            sample_broken = code_lines[0] if code_lines else (student_ans or starter or "(respuesta vacía)")
            target_criterion = missed_criteria[0] if missed_criteria else f"Cumplir la especificación de {node_title}"
            code_fixes.append(
                {
                    "broken_snippet": sample_broken[:180],
                    "fixed_snippet": f"/* Ajustar implementación para: {target_criterion} */",
                    "why": f"Este cambio permite cumplir con el criterio técnico evaluado: {target_criterion}.",
                }
            )
        elif ct in LANGUAGE_CHALLENGE_TYPES and status != "passed" and not code_fixes:
            sample_phrase = student_ans[:180] if student_ans else "(sin respuesta en inglés)"
            target_criterion = missed_criteria[0] if missed_criteria else f"Aplicar estructura natural de {node_title}"
            fixed_target = ref_interactive_sol or f"Apply natural English structure: {target_criterion}"
            code_fixes.append(
                {
                    "broken_snippet": sample_phrase,
                    "fixed_snippet": fixed_target,
                    "why": f"Este cambio corrige la gramática/vocabulario requerido: {target_criterion}.",
                }
            )

        raw_diag = str(raw_item.get("diagnosis") or "").strip()
        if raw_diag:
            diagnosis = raw_diag
        else:
            if status == "passed":
                diagnosis = "Respuesta correcta: cubriste con precisión todos los criterios evaluados en esta pregunta."
            elif status == "partial":
                if covered_criteria and missed_criteria:
                    diagnosis = (
                        f"Respuesta parcial: acertaste en {'; '.join(covered_criteria[:2])}, "
                        f"pero faltó precisar {'; '.join(missed_criteria[:2])}."
                    )
                elif missed_criteria:
                    diagnosis = f"Respuesta parcial: faltó desarrollar {'; '.join(missed_criteria[:2])}."
                else:
                    diagnosis = "Respuesta con observaciones técnicas puntuales a corregir."
            else:
                if missed_criteria:
                    diagnosis = f"Respuesta incompleta o incorrecta: debes demostrar que {'; '.join(missed_criteria[:3])}."
                else:
                    diagnosis = "No se cubrieron los criterios mínimos exigidos en esta pregunta."

        corrected_solution = _clean_fenced_solution(raw_item.get("corrected_solution"))
        if status == "passed" and not code_fixes:
            corrected_solution = None
        elif status != "passed":
            if ct == "dictation" and ref_interactive_sol:
                if not corrected_solution or ref_interactive_sol.lower() not in corrected_solution.lower():
                    corrected_solution = ref_interactive_sol
            elif corrected_solution is None:
                if ref_interactive_sol:
                    corrected_solution = ref_interactive_sol
                elif r_points:
                    if ct in ("debug", "implement"):
                        comment_prefix = "--" if lang == "sql" else ("#" if lang == "python" else "//")
                        corrected_solution = "\n".join(
                            [f"{comment_prefix} Solución de referencia ({node_title}):"]
                            + [f"{comment_prefix} {i + 1}. {pt}" for i, pt in enumerate(r_points)]
                        )
                    else:
                        corrected_solution = "\n".join(f"- {pt}" for pt in r_points)

        reviews_out.append(
            {
                "prompt_id": qid,
                "status": status,
                "diagnosis": diagnosis,
                "code_fixes": code_fixes,
                "corrected_solution": corrected_solution,
            }
        )

    routing = str(raw_routing_suggestion or "").strip()
    if not routing:
        if score >= 8.5:
            routing = f"Dominio sólido en {node_title}: avanza al siguiente nodo del árbol."
        elif score >= 7.0:
            routing = (
                f"Aprobaste {node_title}, pero revisa las correcciones puntuales de tus respuestas "
                "antes de avanzar al siguiente nodo."
            )
        else:
            routing = (
                f"Aún no alcanzas 7.0 en {node_title}: revisa el diagnóstico pregunta por pregunta, "
                "repasa la explicación del nodo y vuelve a intentarlo."
            )

    return (reviews_out, routing)


def evaluate_with_ai(
    *,
    node_title: str,
    story_script: str,
    eval_prompts: list[dict[str, Any]],
    answers_by_prompt: dict[str, str],
    preferred_provider: str = "auto",
    engine_type: str = "concept_tree",
) -> dict[str, Any]:
    """Evalua respuestas a ciegas con rigor socratico 1..10 usando el router multi-IA.

    Cuando engine_type == 'code_lab' o alguna pregunta es 'debug'/'implement'/'trace',
    actua como Senior Dev / Profesor exigente de programacion y bases de datos.
    Cuando engine_type == 'language_studio', evalua gramatica, vocabulario y mecanicas interactivas
    con fallback determinista offline coherente.
    """
    rubric_spec: list[dict[str, Any]] = []
    all_keys: list[str] = []
    has_code_challenge = engine_type == "code_lab"
    has_language_challenge = engine_type == "language_studio"
    has_interactive_language = False

    for q in eval_prompts:
        qid = str(q["id"])
        ct = str(q.get("challenge_type") or "concept").strip().lower()
        lang = str(q.get("language") or "text").strip().lower()
        starter = q.get("starter_code")
        interaction_data = q.get("interaction_data")
        if ct in ("debug", "implement", "trace") or starter:
            has_code_challenge = True
        if ct in LANGUAGE_CHALLENGE_TYPES or lang == "en":
            has_language_challenge = True
        if ct in LANGUAGE_INTERACTIVE_CHALLENGE_TYPES:
            has_interactive_language = True
        pts = []
        for idx, pt in enumerate(q.get("rubric_points", [])):
            key = f"{qid}::{idx}"
            all_keys.append(key)
            pts.append({"key": key, "criterion": pt})
        item_spec: dict[str, Any] = {
            "prompt_id": qid,
            "challenge_type": ct,
            "language": lang,
            "question": q.get("question", ""),
            "student_answer": answers_by_prompt.get(qid, "").strip(),
            "rubric_points": pts,
        }
        if starter:
            item_spec["starter_code"] = str(starter)
        if isinstance(interaction_data, dict) and interaction_data:
            item_spec["interaction_data"] = interaction_data
        rubric_spec.append(item_spec)

    senior_dev_rules = ""
    if has_language_challenge:
        senior_dev_rules = (
            "\nMODO PROFESOR DE INGLES (`language_studio`):\n"
            "- Evalua las respuestas del estudiante como un profesor universitario de ingles exigente y bilingue.\n"
            "- Revisa gramatica real en ingles (conjugacion `verb to be`, `-s/-es` de 3a persona singular en Present Simple, "
            "uso correcto de auxiliares `do/does` y `don't/doesn't` sin duplicar `-s` en el verbo base, concordancia "
            "`there is / there are`, `quantifiers` como `some/any/much/many/a lot of`, orden Sujeto + Verbo + Complemento "
            "sin omitir pronombres sujeto), uso preciso del vocabulario del nodo y claridad comunicativa.\n"
            "- En `fill_blank`, `translate` y `speaking_prompt`, exige que la respuesta este escrita en ingles correcto "
            "(si responde solo en espanol cuando se pedia ingles, califica bajo).\n"
            "- MECANICAS INTERACTIVAS (usa `interaction_data` como referencia exacta):\n"
            "  * `word_order`: el estudiante envia la oracion armada; compara contra `interaction_data.tiles` y penaliza "
            "si incluyo algun distractor de `interaction_data.distractors` o altero el orden natural.\n"
            "  * `categorize`: el estudiante envia lineas `Categoria: item1, item2`; valida contra "
            "`interaction_data.categories`, `items` y `expected_map`.\n"
            "  * `find_error`: el estudiante envia `'Sin error'` o `'Error: <token> -> Corrección: <texto>'`; valida contra "
            "`interaction_data.sentence`, `error_token`, `correction` y `allow_no_error`.\n"
            "  * `dictation`: el estudiante envia su transcripcion; compara palabra por palabra contra "
            "`interaction_data.audio_text` e incluye siempre la frase original `audio_text` en `corrected_solution` cuando "
            "haya errores u omisiones.\n"
            "- En `prompt_reviews` y `code_fixes`: cuando la frase del estudiante tenga errores gramaticales, de vocabulario "
            "o suene poco natural, llena `code_fixes` mostrando cada error puntual (`broken_snippet`: Tu frase exacta con el error, "
            "`fixed_snippet`: Correccion natural en ingles, `why`: explicacion breve en espanol iniciando con 'Este cambio corrige...') "
            "y entrega una respuesta modelo natural y completa en ingles en `corrected_solution` cuando haya mejoras o errores.\n"
            "- Escribe `diagnosis`, `imprecisions`, `routing_suggestion` y `re_explanation` en espanol claro con los ejemplos "
            "puntuales corregidos en ingles.\n"
        )
    elif has_code_challenge:
        senior_dev_rules = (
            "\nMODO SENIOR DEV / PROFESOR EXIGENTE DE CODIGO (`code_lab`):\n"
            "- Evalua el codigo y las trazas del estudiante como un Senior Developer y profesor universitario riguroso.\n"
            "- Revisa logica, tipos, sintaxis clave (`extends`/`implements`, `super()`, `@Override`, encapsulamiento, "
            "manejo de excepciones `try/catch/throws`, `null`/casos borde, mutacion de colecciones o consultas SQL "
            "`JOIN`, `GROUP BY`, `HAVING`).\n"
            "- En desafios `debug` o `implement`, compara `student_answer` contra `starter_code`: si el estudiante "
            "dejo el `starter_code` sin corregir el bug o con el `TODO` vacio, NO otorgues esos puntos y califica bajo.\n"
            "- En `imprecisions`, señala explicitamente QUE LINEA, condicion, firma o detalle tecnico falla.\n"
            "- Para retos de codigo (`debug`, `implement`, `trace`): si el codigo del estudiante tiene errores o "
            "imprecisiones, DEBES llenar `code_fixes` dentro del `prompt_reviews` de esa pregunta señalando "
            "EXACTAMENTE cada fragmento erroneo del codigo del estudiante (`broken_snippet`), el fragmento corregido "
            "(`fixed_snippet`) y el motivo concreto (`why`: explicacion explicita tipo 'Este cambio permite...' o "
            "'Sin esto ocurre...'), y ademas `corrected_solution` con la solucion limpia completa solo si "
            "`status != \"passed\"` (o si hubo imprecisiones).\n"
            "- Si `score < 7.0`, en `re_explanation` incluye una explicacion directa del fallo acompañada de un "
            "bloque de codigo Markdown limpio (ej. ```java ... ``` o ```sql ... ```) mostrando la correccion o guia.\n"
        )

    system_prompt = (
        "Eres el Evaluador Socratico de Brotal. Evaluas respuestas a ciegas de un estudiante universitario "
        "con rigor del 1.0 al 10.0 (7.0 o mas aprueba). No regales puntos si la respuesta es vaga o vacia.\n"
        "REGLA DE CONSISTENCIA 10/10: Si pones una nota menor a 10.0, DEBES incluir al menos una observación "
        "concreta en `imprecisions` explicando qué faltó o qué se puede mejorar para llegar a 10.0. "
        "Nunca descuentes puntos sin explicar por qué.\n"
        "REVISION PREGUNTA POR PREGUNTA OBLIGATORIA:\n"
        "- Devuelve `prompt_reviews` con 1 item por cada `prompt_id` evaluado (`status`: 'passed' | 'partial' | 'failed', "
        "`diagnosis`, `code_fixes` y `corrected_solution`).\n"
        "- Devuelve `routing_suggestion`: 1 oracion accionable indicando si conviene repasar un prerrequisito, "
        "reintentar este nodo o avanzar al siguiente.\n"
        "- NUNCA incluyas claves internas como `q1::0` o `q2::1` en los textos visibles de `imprecisions`, `diagnosis` ni `re_explanation`."
        f"{senior_dev_rules}\n"
        "Responde UNICAMENTE un objeto JSON valido con esta estructura exacta:\n"
        "{\n"
        '  "score": 7.5,\n'
        '  "covered_points": ["q1::0", "q1::1"],\n'
        '  "imprecisions": ["En linea X: falta validar null / usar equals() en vez de =="],\n'
        '  "re_explanation": "Breve re-explicacion conversada y bloque de codigo Markdown si aplica (solo si score < 7.0, vacio si >= 7.0)",\n'
        '  "routing_suggestion": "Reintenta este nodo corrigiendo la comparacion de Strings antes de avanzar.",\n'
        '  "prompt_reviews": [\n'
        "    {\n"
        '      "prompt_id": "q1",\n'
        '      "status": "partial",\n'
        '      "diagnosis": "Identificaste el flujo general pero mantuviste la comparacion por referencia.",\n'
        '      "code_fixes": [\n'
        "        {\n"
        '          "broken_snippet": "if (actual == codigo)",\n'
        '          "fixed_snippet": "if (codigo != null && codigo.equals(actual))",\n'
        '          "why": "Este cambio permite comparar el contenido de los Strings por valor y evita NullPointerException."\n'
        "        }\n"
        "      ],\n"
        '      "corrected_solution": "public boolean validar(...) {\\n    ...\\n}"\n'
        "    }\n"
        "  ]\n"
        "}"
    )
    user_prompt = json.dumps(
        {
            "node_title": node_title,
            "engine_type": engine_type,
            "reference_story": story_script[:2000],
            "evaluation_items": rubric_spec,
        },
        ensure_ascii=False,
    )

    try:
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
    except (AiProviderError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        if has_language_challenge or has_interactive_language:
            return evaluate_language_fallback_deterministic(
                node_title=node_title,
                eval_prompts=eval_prompts,
                answers_by_prompt=answers_by_prompt,
            )
        raise

    valid_keys = set(all_keys)
    raw_covered = parsed.get("covered_points") or []
    covered_points = [str(k) for k in raw_covered if str(k) in valid_keys]

    raw_score = parsed.get("score")
    if isinstance(raw_score, (int, float)):
        score = round(max(1.0, min(10.0, float(raw_score))), 1)
    else:
        ratio = len(covered_points) / len(all_keys) if all_keys else 0.0
        score = round(1.0 + 9.0 * ratio, 1)

    imprecisions = [
        re.sub(r"^(?:q\d+|p\d+)(?:::\d+)?\s*[:\-–]\s*", "", str(x).strip(), flags=re.IGNORECASE).strip()
        for x in (parsed.get("imprecisions") or [])
        if str(x).strip()
    ]
    imprecisions = [x for x in imprecisions if x]
    if all_keys and len(set(covered_points)) == len(valid_keys) and not imprecisions and score < 10.0:
        score = 10.0

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

    prompt_reviews, routing_suggestion = build_prompt_reviews_and_routing(
        node_title=node_title,
        eval_prompts=eval_prompts,
        answers_by_prompt=answers_by_prompt,
        covered_points=covered_points,
        score=score,
        imprecisions=imprecisions,
        raw_prompt_reviews=parsed.get("prompt_reviews"),
        raw_routing_suggestion=parsed.get("routing_suggestion"),
    )

    return {
        "score": score,
        "covered_points": covered_points,
        "imprecisions": imprecisions,
        "re_explanation": re_explanation,
        "prompt_reviews": prompt_reviews,
        "routing_suggestion": routing_suggestion,
        "provider": completion.provider,
        "model": completion.model,
    }


evaluate_answers_with_ai = evaluate_with_ai


def _strip_bullets(story: str) -> str:
    lines = story.splitlines()
    cleaned_lines: list[str] = []
    in_code_block = False
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            cleaned_lines.append(stripped)
            continue
        if in_code_block:
            cleaned_lines.append(ln.rstrip())
            continue
        if not stripped:
            cleaned_lines.append("")
            continue
        s = re.sub(r"^[-*•]\s+", "", stripped)
        s = re.sub(r"^\d+[.)]\s+", "", s)
        cleaned_lines.append(s)
    prose = "\n".join(cleaned_lines)
    return re.sub(r"\n{3,}", "\n\n", prose).strip()


def explanation_style_instruction(explanation_style: str, world_metaphor: str) -> str:
    if explanation_style == "direct":
        return (
            "ESTILO DIRECTO (`direct`): Escribe una explicacion tecnica directa, precisa y clara en 2 a 3 parrafos "
            "fluidos (~180 a 240 palabras). PROHIBIDO usar 'Imagina...', 'Situemonos en...' o metaforas forzadas. "
            "Ve directo a la definicion operativa, el mecanismo tecnico y que problema concreto resuelve."
        )
    if explanation_style == "structured":
        return (
            "ESTILO ESTRUCTURADO (`structured`): Escribe 3 parrafos claros y bien encadenados (~180 a 240 palabras) "
            "siguiendo el orden exacto: (1) Concepto central y funcion tecnica -> (2) Relacion de causa-efecto y mecanismo "
            "interno -> (3) Ejemplo concreto de aplicacion real. Sin listas secas telegraficas ni vinetas."
        )
    return (
        f"ESTILO NARRATIVO (`narrative`): Escribe una historia conversada continua en 2 a 3 parrafos (~180 a 240 palabras) "
        f"usando la metafora del mundo (`{world_metaphor}`), explicando causa-efecto y que problema real resuelve. "
        "PROHIBIDO usar listas con vinetas o numeraciones."
    )


def question_style_instruction(question_style: str, world_metaphor: str) -> str:
    if question_style == "scenario":
        return (
            f"ESTILO ESCENARIO (`scenario`): Formula preguntas basadas en un caso o situacion aplicada con contexto "
            f"(diagnostico de fallos, toma de decision o escenario dentro de `{world_metaphor}` o de la ingenieria real)."
        )
    return (
        "ESTILO DIRECTO (`direct`): Formula preguntas breves, precisas y directas de 1 a 2 lineas (tipo examen real), "
        "sin rodeos narrativos ni introducciones largas."
    )


def _fallback_story_code_block(node_title: str, language: str = "java") -> str:
    lang = language if language in ("java", "sql", "python", "c") else "java"
    clean_cls = re.sub(r"[^a-zA-Z0-9]", "", node_title.title())[:16] or "EjemploNodo"
    if not clean_cls[0].isalpha():
        clean_cls = f"Nodo{clean_cls}"
    if lang == "sql":
        return (
            "```sql\n"
            f"-- Ejemplo aplicado: {node_title}\n"
            "SELECT c.id_curso, c.nombre, COUNT(i.id_estudiante) AS inscritos\n"
            "FROM cursos c\n"
            "INNER JOIN inscripciones i ON i.id_curso = c.id_curso\n"
            "GROUP BY c.id_curso, c.nombre\n"
            "HAVING COUNT(i.id_estudiante) >= 1\n"
            "ORDER BY inscritos DESC;\n"
            "```"
        )
    if lang == "python":
        return (
            "```python\n"
            f"# Ejemplo aplicado: {node_title}\n"
            "def filtrar_activos(valores: list[int], minimo: int = 0) -> list[int]:\n"
            "    resultado: list[int] = []\n"
            "    for actual in valores:\n"
            "        if actual >= minimo:\n"
            "            resultado.append(actual)\n"
            "    return resultado\n"
            "```"
        )
    if lang == "c":
        return (
            "```c\n"
            f"/* Ejemplo aplicado: {node_title} */\n"
            "int sumar_rango(const int *datos, int n) {\n"
            "    int acumulador = 0;\n"
            "    for (int i = 0; i < n; i++) {\n"
            "        acumulador += datos[i];\n"
            "    }\n"
            "    return acumulador;\n"
            "}\n"
            "```"
        )
    return (
        "```java\n"
        f"public class {clean_cls}Demo {{\n"
        "    private final String identificador;\n\n"
        f"    public {clean_cls}Demo(String identificador) {{\n"
        "        this.identificador = identificador != null ? identificador.trim() : \"\";\n"
        "    }\n\n"
        "    public boolean coincideCon(String candidato) {\n"
        "        return candidato != null && this.identificador.equals(candidato);\n"
        "    }\n"
        "}\n"
        "```"
    )


def _fallback_language_story_examples(node_title: str) -> str:
    return (
        "```en\n"
        f"[+] Affirmative: She studies {node_title} every morning, and there are some notes on her desk.\n"
        "[-] Negative:    She doesn't skip practice, and there isn't any confusion about the main rule.\n"
        "[?] Question:    Does she review vocabulary every day? / Are there any exercises left?\n"
        "```"
    )


def regenerate_story_with_ai(
    *,
    course_title: str,
    world_metaphor: str | None,
    node_title: str,
    node_summary: str,
    current_story: str,
    eval_prompts: list[dict[str, Any]],
    preferred_provider: str = "auto",
    explanation_style: str = "narrative",
    engine_type: str = "concept_tree",
) -> tuple[str, str]:
    """Genera una explicacion alternativa respetando explanation_style ('narrative' | 'direct' | 'structured').

    Siempre 2 a 3 parrafos continuos (~180-240 palabras de prosa), sin listas con vinetas.
    Marca de 3 a 6 conceptos clave en **negrita** y, si engine_type == 'code_lab', incluye 1 bloque de codigo cercado.
    Garantiza cobertura explicita de todos los rubric_points de eval_prompts.
    Devuelve (new_story_script, provider_used).
    """
    rubric_points = [
        str(pt).strip()
        for q in eval_prompts
        for pt in (q.get("rubric_points") or [])
        if str(pt).strip()
    ]
    prompt_questions = [
        str(q.get("question") or "").strip()
        for q in eval_prompts
        if str(q.get("question") or "").strip()
    ]
    is_language_studio = engine_type == "language_studio" or any(
        str(q.get("challenge_type") or "concept") in LANGUAGE_CHALLENGE_TYPES
        or str(q.get("language") or "").strip().lower() == "en"
        for q in eval_prompts
    )
    is_code_lab = not is_language_studio and (
        engine_type == "code_lab"
        or any(
            str(q.get("challenge_type") or "concept") in ("debug", "implement", "trace") or q.get("starter_code")
            for q in eval_prompts
        )
    )
    inferred_lang = (
        "en"
        if is_language_studio
        else next(
            (
                str(q.get("language")).strip().lower()
                for q in eval_prompts
                if str(q.get("language") or "").strip().lower() in ("java", "sql", "python", "c")
            ),
            "java" if is_code_lab else "text",
        )
    )
    metaphor_hint = world_metaphor or f"Taller practico de {course_title}"
    style_rule = explanation_style_instruction(explanation_style, metaphor_hint)

    code_lab_story_rule = ""
    if is_language_studio:
        code_lab_story_rule = (
            "\n- MODO `language_studio` ACTIVO (Ingles universitario): Escribe la explicacion en espanol claro y "
            "conversado marcando las **reglas gramaticales y de vocabulario clave en `**negrita**`**, explicando las "
            "estructuras **afirmativa, negativa e interrogativa**, las **trampas tipicas de hispanohablantes** y "
            "**ejemplos concretos en ingles** claramente diferenciados (en un bloque ```en ... ``` y/o entre comillas "
            "con traduccion breve entre parentesis). Cubre explicitamente todo el vocabulario y gramatica evaluados."
        )
    elif is_code_lab:
        code_lab_story_rule = (
            f"\n- MODO `code_lab` ACTIVO (lenguaje `{inferred_lang}`): Incluye 1 ejemplo de codigo real corto y limpio "
            f"(de 10 a 22 lineas) en un bloque Markdown cercado (```{inferred_lang} ... ```) — o hasta 2 micro-fragmentos "
            "de 4 a 8 lineas si contrastan un error vs. su correccion — que ilustre las sintaxis, anotaciones y reglas "
            "clave del nodo."
        )

    try:
        system_prompt = (
            "Eres el autor pedagogico de Brotal. Tu tarea es explicar un concepto universitario "
            "en espanol en 2 a 3 parrafos continuos de prosa (~180 a 240 palabras).\n"
            f"{style_rule}\n"
            "REGLAS INNEGOCIABLES:\n"
            "- CONTRATO ESTRICTO DE COBERTURA EXPLICACION <-> PREGUNTAS: CADA `rubric_point` listado y toda sintaxis, "
            "anotacion o mecanismo evaluado en `eval_prompts` DEBE quedar explicitamente explicado y ejemplificado en esta "
            "nueva explicacion (ej. si la rubrica o pregunta evalua `@Override`, `super()`, `equals()`, `GROUP BY` o `HAVING`, "
            "debes enseñarlo explicitamente).\n"
            "- DESTACADOS VISUALES: Marca entre 3 y 6 conceptos, reglas o palabras clave fundamentales por historia con "
            "`**negrita**` (ej. `**polimorfismo dinamico**`, `**@Override**`, `**pasa por valor**`)."
            f"{code_lab_story_rule}\n"
            "- PROHIBIDO usar listas con vinetas, numeraciones o encabezados markdown: entrega unicamente los parrafos "
            "de prosa (y el bloque cercado si es `code_lab` o `language_studio`)."
        )
        user_prompt = (
            f"Ramo: {course_title}\n"
            f"Motor: {engine_type} (lenguaje: {inferred_lang})\n"
            f"Estilo solicitado: {explanation_style}\n"
            f"Metafora del mundo (solo si el estilo es narrative): {metaphor_hint}\n"
            f"Nodo: {node_title} ({node_summary})\n"
            f"Preguntas del nodo que tu explicacion debe respaldar: {' | '.join(prompt_questions)}\n"
            f"Rubric points OBLIGATORIOS a cubrir y ejemplificar: {', '.join(rubric_points)}\n"
            f"Explicacion anterior (usa otro enfoque/ejemplo distinto manteniendo ~180-240 palabras en 2 a 3 parrafos):\n"
            f"{current_story}\n"
        )
        comp = complete_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            preferred_provider=preferred_provider,
            json_mode=False,
            temperature=0.55,
        )
        return (_strip_bullets(comp.text), comp.provider)
    except AiProviderError:
        concepts_prose = ". Asimismo, ".join(rubric_points) if rubric_points else node_summary
        if is_language_studio:
            alt_en = _strip_bullets(
                f"Para dominar **{node_title}** en {course_title}, conviene fijar primero la regla en español antes de "
                f"producir en inglés: {node_summary}. Recuerda mantener siempre el **orden Sujeto + Verbo + Complemento** "
                f"en oraciones **afirmativas**, usar el **auxiliar correspondiente** en **negativas e interrogativas** "
                f"y cubrir cada punto evaluado: {concepts_prose}.\n\n"
                f"{_fallback_language_story_examples(node_title)}\n\n"
                f"Evita la **trampa típica de hispanohablantes** de traducir palabra por palabra omitiendo el sujeto "
                f"(por ejemplo, di `\"It is important to practice every day\"` — es importante practicar cada día — "
                f"en lugar de empezar directamente con `\"Is important\"`)."
            )
            return (alt_en, "local_fallback")
        code_block_section = (
            f"\n\n{_fallback_story_code_block(node_title, inferred_lang)}\n\n"
            if is_code_lab
            else "\n\n"
        )
        if explanation_style == "direct":
            alt = _strip_bullets(
                f"**{node_title}** en {course_title} define un **mecanismo técnico** fundamental cuyo objetivo directo es "
                f"resolver: {node_summary}. Su operación se basa en **reglas verificables** que determinan el comportamiento "
                f"exacto del sistema sin ambigüedades.\n\n"
                f"En términos técnicos, el funcionamiento exige cumplir que {concepts_prose}. Cada **invariante** y condición "
                f"afecta de forma directa la eficiencia, corrección y estabilidad de la implementación."
                f"{code_block_section}"
                f"Para validar **{node_title}** en la práctica, se comprueba directamente que se cumplan estas propiedades "
                f"técnicas ante entradas normales y **casos de borde**."
            )
        elif explanation_style == "structured":
            alt = _strip_bullets(
                f"Concepto central: **{node_title}** dentro de {course_title} establece la **base estructural** para abordar "
                f"{node_summary}, definiendo los límites y responsabilidades del componente en el sistema.\n\n"
                f"Causa y efecto: El mecanismo opera garantizando que {concepts_prose}. Cuando una de estas **condiciones críticas** "
                f"varía, el **efecto directo** se propaga sobre el rendimiento y la consistencia del resultado."
                f"{code_block_section}"
                f"Ejemplo concreto: En una implementación real de {course_title}, aplicar **{node_title}** permite verificar "
                f"paso a paso cada criterio técnico y diagnosticar con exactitud cualquier desviación."
            )
        else:
            alt = _strip_bullets(
                f"Míralo ahora desde otro ángulo operativo dentro de {metaphor_hint}. Cuando nos enfrentamos a **{node_title}** "
                f"en {course_title}, el error típico es quedarse en la definición de memoria en vez de seguir el **flujo real** "
                f"del sistema y entender qué problema concreto resuelve: {node_summary}.\n\n"
                f"Imagina que tienes que diagnosticarlo en vivo paso a paso cuando algo falla en {metaphor_hint}: primero "
                f"confirmas la **causa y efecto** verificando que {concepts_prose}. Cada una de estas piezas protege el **invariante** "
                f"para mantener la estabilidad del diseño."
                f"{code_block_section}"
                f"Al conectar cada mecanismo con su **consecuencia práctica** dentro de {metaphor_hint}, ya no necesitas "
                f"memorizar definiciones aisladas, porque puedes anticipar qué ocurre si una condición cambia y justificar "
                f"tu decisión técnica con claridad."
            )
        return (alt, "local_fallback")


def _alternate_starter_code(
    *,
    language: str,
    challenge_type: str,
    node_title: str,
    prev_starter: str | None,
    idx: int = 1,
) -> str:
    """Genera un starter_code alternativo distinto al anterior para regeneracion en code_lab."""
    lang = language if language in ("java", "sql", "python", "c") else "java"
    clean_cls = re.sub(r"[^a-zA-Z0-9]", "", node_title.title())[:16] or f"Reto{idx}"
    if not clean_cls[0].isalpha():
        clean_cls = f"Nodo{clean_cls}"

    variants_java: dict[str, list[str]] = {
        "debug": [
            (
                f"// Variante A (Debugging): {node_title}\n"
                "import java.util.Map;\n\n"
                f"public class {clean_cls}Validator {{\n"
                "    public int obtenerPuntaje(Map<String, Integer> tabla, String clave) {\n"
                "        // BUG: unboxing directo de null lanza NullPointerException si la clave no existe\n"
                "        int valor = tabla.get(clave);\n"
                "        return valor >= 0 ? valor : 0;\n"
                "    }\n"
                "}"
            ),
            (
                f"// Variante B (Debugging): {node_title}\n"
                "import java.util.List;\n\n"
                f"public class {clean_cls}Processor {{\n"
                "    public void limpiarInactivos(List<String> codigos) {\n"
                "        // BUG: remover en for-each lanza ConcurrentModificationException\n"
                "        for (String c : codigos) {\n"
                "            if (c == null || c.isBlank()) {\n"
                "                codigos.remove(c);\n"
                "            }\n"
                "        }\n"
                "    }\n"
                "}"
            ),
        ],
        "implement": [
            "// Implementa tu solución en Java aquí",
            f"// Implementa tu solución en Java para: {node_title}",
        ],
        "trace": [
            (
                f"// Variante A (Traza JVM): {node_title}\n"
                "class Base {\n"
                "    public String etiqueta() { return \"B\"; }\n"
                "    public String resumen() { return \"[\" + etiqueta() + \"]\"; }\n"
                "}\n"
                f"class {clean_cls}Sub extends Base {{\n"
                "    @Override\n"
                "    public String etiqueta() { return \"S\"; }\n"
                "}\n"
                f"Base obj = new {clean_cls}Sub();\n"
                "System.out.println(obj.resumen());"
            ),
            (
                f"// Variante B (Traza JVM): {node_title}\n"
                "int resultado = 10;\n"
                "try {\n"
                "    resultado += 5;\n"
                "    if (resultado > 12) throw new IllegalStateException(\"limite\");\n"
                "    resultado += 100;\n"
                "} catch (IllegalStateException e) {\n"
                "    resultado *= 2;\n"
                "} finally {\n"
                "    resultado -= 3;\n"
                "}\n"
                "System.out.println(resultado);"
            ),
        ],
    }

    if lang == "sql":
        if challenge_type == "implement":
            sql_impl_a = "-- Implementa tu consulta SQL aquí"
            sql_impl_b = f"-- Implementa tu consulta SQL para: {node_title}"
            return sql_impl_b if (prev_starter and prev_starter.strip() == sql_impl_a) else sql_impl_a
        sql_A = (
            f"-- Variante A ({challenge_type.upper()}): {node_title}\n"
            "SELECT e.id, e.nombre, AVG(n.calificacion) AS promedio\n"
            "FROM estudiantes e\n"
            "INNER JOIN notas n ON n.estudiante_id = e.id\n"
            "WHERE AVG(n.calificacion) >= 4.0\n"
            "GROUP BY e.id, e.nombre;"
        )
        sql_B = (
            f"-- Variante B ({challenge_type.upper()}): {node_title}\n"
            "SELECT c.codigo, COUNT(m.id) AS total\n"
            "FROM cursos c\n"
            "LEFT JOIN matriculas m ON m.curso_id = c.id\n"
            "GROUP BY c.codigo\n"
            "HAVING COUNT(m.id) > 0\n"
            "ORDER BY total DESC;"
        )
        return sql_B if (prev_starter and "Variante A" in prev_starter) else sql_A

    pool = variants_java.get(challenge_type, variants_java["implement"])
    if prev_starter and prev_starter.strip() == pool[0].strip():
        return pool[1]
    return pool[0]


def regenerate_questions_with_ai(
    *,
    course_title: str,
    world_metaphor: str | None,
    node_title: str,
    node_summary: str,
    story_script: str,
    eval_prompts: list[dict[str, Any]],
    preferred_provider: str = "auto",
    question_style: str = "direct",
    engine_type: str = "concept_tree",
) -> tuple[list[dict[str, Any]], str]:
    """Redacta preguntas nuevas y distintas evaluando exactamente los mismos rubric_points segun question_style."""
    metaphor_hint = world_metaphor or f"Taller practico de {course_title}"
    q_rule = question_style_instruction(question_style, metaphor_hint)
    source_prompts = eval_prompts or [
        {
            "id": "q1",
            "question": f"¿Como funciona {node_title} en {course_title}?",
            "rubric_points": [f"Explica el concepto central de {node_title}"],
        }
    ]
    is_language_studio = engine_type == "language_studio" or any(
        str(p.get("challenge_type") or "concept") in LANGUAGE_CHALLENGE_TYPES
        or str(p.get("language") or "").strip().lower() == "en"
        for p in source_prompts
    )
    is_code_lab = not is_language_studio and (
        engine_type == "code_lab"
        or any(
            str(p.get("challenge_type") or "concept") in ("debug", "implement", "trace") or p.get("starter_code")
            for p in source_prompts
        )
    )
    inferred_lang = (
        "en"
        if is_language_studio
        else next(
            (
                str(p.get("language"))
                for p in source_prompts
                if str(p.get("language") or "") in ("java", "sql", "python", "c")
            ),
            "java" if is_code_lab else "text",
        )
    )

    code_lab_regen_rule = ""
    if is_language_studio:
        code_lab_regen_rule = (
            "\n5. MODO `language_studio` ACTIVO (Ingles universitario, `\"language\": \"en\"`, `\"starter_code\": null`): "
            "Mezcla retos de produccion a ciegas con interferencia real espanol->ingles combinando los 4 tipos interactivos "
            "(`\"word_order\"`, `\"categorize\"`, `\"find_error\"`, `\"dictation\"`) con `\"fill_blank\"`, `\"translate\"` y "
            "`\"speaking_prompt\"`.\n"
            "   - Para los 4 tipos interactivos DEBES incluir `\"interaction_data\"` valido:\n"
            "     * `word_order`: `{\"tiles\": [>=4 bloques de la oracion valida], \"distractors\": [1-2 distractores L1-ES como do/does, is/are, much/many], \"hint_es\": \"...\"}`\n"
            "     * `categorize`: `{\"categories\": [>=2 categorias], \"items\": [>=4 bloques], \"expected_map\": {\"item\": \"categoria\"}}`\n"
            "     * `find_error`: `{\"sentence\": \"oracion en ingles\", \"tokens\": [>=4 tokens], \"allow_no_error\": true, \"error_token\": \"...\"|null, \"correction\": \"...\"|null}`\n"
            "     * `dictation`: `{\"audio_text\": \"frase en ingles no vacia\", \"accent\": \"us\"|\"gb\"|\"au\", \"hint_es\": \"...\"}`\n"
        )
    elif is_code_lab:
        code_lab_regen_rule = (
            f"\n5. MODO `code_lab` ACTIVO (lenguaje `{inferred_lang}`): Manten o varia los tipos de reto "
            "(`\"challenge_type\": \"debug\" | \"implement\" | \"trace\" | \"concept\"`, "
            f"`\"language\": \"{inferred_lang}\"`) respetando estrictamente estas reglas de `starter_code`:\n"
            "   - `debug` y `trace`: SI incluyen un NUEVO codigo completo y distinto al anterior en `starter_code`, "
            "SIEMPRE formateado en multiples lineas con `\\n` e indentacion limpia de 2/4 espacios (NUNCA todo en una sola linea).\n"
            "   - PROHIBIDO DUPLICAR CODIGO EN `question`: Cuando exista `starter_code` (`debug` o `trace`), "
            "`question` NUNCA debe repetir ni incluir el codigo (solo debe indicar la tarea: que bug corregir o que trazar).\n"
            "   - `implement` en nodos basicos/intermedios (clases, constructores, arreglos, herencia basica, "
            "excepciones basicas): `starter_code` DEBE ir vacio (`\"\"`) o solo un comentario de 1 linea "
            "(`// Implementa tu solución en Java aquí`) — PROHIBIDO regalar el esqueleto resuelto de la clase/metodos con `// TODO`.\n"
            "   - `implement` en nodos avanzados (patrones de diseno, Swing/MVC, integraciones): solo puede incluir "
            "clases/interfaces auxiliares de contexto que el estudiante usara, NUNCA el esqueleto ya resuelto del metodo "
            "o clase que debe construir.\n"
        )

    try:
        system_prompt = (
            "Eres el Evaluador Socratico de Brotal. Tu tarea es redactar PREGUNTAS NUEVAS Y DISTINTAS "
            "que evaluen EXACTAMENTE los mismos `rubric_points` de cada pregunta original.\n"
            f"{q_rule}\n"
            "REGLAS OBLIGATORIAS:\n"
            "1. Conserva los mismos `id` y los mismos `rubric_points` de cada item.\n"
            "2. Cambia por completo la formulacion de cada `question` respetando el estilo solicitado.\n"
            "3. CONTRATO ESTRICTO DE COBERTURA: PROHIBIDO exigir en las preguntas o en el codigo anotaciones, clases, "
            "sintaxis o conceptos que NO esten presentes y explicados en `story_script` ni en `node_summary`.\n"
            "4. Responde UNICAMENTE un objeto JSON valido con la clave `eval_prompts`:\n"
            '{"eval_prompts": [{"id": "q1", "question": "Nueva pregunta...", "rubric_points": ["..."], '
            '"challenge_type": "concept", "language": "text", "starter_code": null}]}'
            f"{code_lab_regen_rule}"
        )
        user_prompt = json.dumps(
            {
                "course_title": course_title,
                "engine_type": engine_type,
                "question_style": question_style,
                "world_metaphor": metaphor_hint,
                "node_title": node_title,
                "node_summary": node_summary,
                "story_script": story_script[:1500],
                "current_eval_prompts": source_prompts,
            },
            ensure_ascii=False,
        )
        comp = complete_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            preferred_provider=preferred_provider,
            json_mode=True,
            temperature=0.65,
        )
        parsed = extract_json_object(comp.text)
        raw_list = parsed.get("eval_prompts")
        if not isinstance(raw_list, list) or not raw_list:
            raise ValueError("Respuesta sin eval_prompts validos")

        items_by_id = {
            str(item.get("id")): item for item in raw_list if isinstance(item, dict)
        }
        updated: list[dict[str, Any]] = []
        for idx, orig in enumerate(source_prompts):
            qid = str(orig.get("id") or f"q{idx+1}")
            pts = [str(p) for p in (orig.get("rubric_points") or [])]
            ai_item = items_by_id.get(qid)
            if ai_item is None and idx < len(raw_list) and isinstance(raw_list[idx], dict):
                ai_item = raw_list[idx]
            ai_item = ai_item or {}

            candidate_q = str(ai_item.get("question") or "").strip()
            if not candidate_q or candidate_q == str(orig.get("question") or "").strip():
                focus = "; ".join(pts[:2]) if pts else node_summary
                if question_style == "scenario":
                    candidate_q = (
                        f"En un escenario aplicado dentro de {metaphor_hint}, ¿como utilizarias {node_title} "
                        f"para resolver un caso considerando: {focus}?"
                    )
                else:
                    candidate_q = f"En {node_title}, explica de forma precisa como opera y por que es clave que: {focus}."

            orig_ct = str(orig.get("challenge_type") or "concept").strip().lower()
            raw_ct = str(ai_item.get("challenge_type") or orig_ct).strip().lower()
            ct = (
                raw_ct
                if raw_ct in ALL_VALID_CHALLENGE_TYPES
                else (orig_ct if orig_ct in ALL_VALID_CHALLENGE_TYPES else "concept")
            )
            lang = str(ai_item.get("language") or orig.get("language") or inferred_lang).strip().lower()
            if lang in ("english", "eng", "en-us", "en-gb", "en-au"):
                lang = "en"
            if ct in LANGUAGE_CHALLENGE_TYPES or is_language_studio:
                lang = "en"
            elif lang not in ("java", "sql", "python", "c", "en", "text"):
                lang = inferred_lang

            starter: str | None = None
            raw_starter = ai_item.get("starter_code")
            if isinstance(raw_starter, str):
                starter = raw_starter.strip()

            if ct in ("debug", "trace"):
                prev_starter = str(orig.get("starter_code") or "").strip() or None
                if not starter or (prev_starter and starter == prev_starter):
                    starter = _alternate_starter_code(
                        language=lang,
                        challenge_type=ct,
                        node_title=node_title,
                        prev_starter=prev_starter,
                        idx=idx + 1,
                    )
            elif ct == "implement" and starter is None:
                prev_starter = str(orig.get("starter_code") or "").strip() or None
                starter = _alternate_starter_code(
                    language=lang,
                    challenge_type="implement",
                    node_title=node_title,
                    prev_starter=prev_starter,
                    idx=idx + 1,
                )

            final_starter = starter if ct in ("debug", "implement", "trace") else None
            clean_q, clean_starter = sanitize_code_prompt(candidate_q, final_starter, lang)
            interaction_data = normalize_language_interaction_data(
                ct,
                ai_item.get("interaction_data"),
                question=clean_q,
                node_title=node_title,
                idx=idx,
            )

            updated.append(
                {
                    "id": qid,
                    "question": clean_q,
                    "rubric_points": pts,
                    "challenge_type": ct,
                    "language": lang,
                    "starter_code": clean_starter,
                    "interaction_data": interaction_data,
                }
            )
        return (updated, comp.provider)
    except (AiProviderError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        if question_style == "scenario":
            templates = [
                "En un escenario de falla en vivo dentro de {metaphor}: ¿como diagnosticarias y justificarias {node} asegurando que {focus}?",
                "Si tuvieras que defender una decision de diseno en {metaphor} sobre {node}, ¿como conectarias en la practica que {focus}?",
                "Ante un caso concreto de {course} dentro de {metaphor}: ¿que ocurriria paso a paso con {node} respecto a {focus}?",
                "Comparando alternativas dentro de {metaphor}, ¿por que es determinante en {node} tener en cuenta que {focus}?",
            ]
        else:
            templates = [
                "Explica de forma directa en {node} como se cumple y por que es necesario que {focus}.",
                "Define con precision tecnica el mecanismo de {node} respecto a: {focus}.",
                "¿Cual es la relacion tecnica exacta en {node} ({course}) cuando se evalua que {focus}?",
                "Justifica brevemente en 2 lineas por que en {node} resulta clave que {focus}.",
            ]
        updated_fallback: list[dict[str, Any]] = []
        for idx, orig in enumerate(source_prompts):
            qid = str(orig.get("id") or f"q{idx+1}")
            pts = [str(p) for p in (orig.get("rubric_points") or [])]
            prev_q = str(orig.get("question") or "").strip()
            focus = " y ".join(p.rstrip(".") for p in pts[:2]) if pts else (node_summary or node_title)
            ct = str(orig.get("challenge_type") or "concept").strip().lower()
            if ct not in ALL_VALID_CHALLENGE_TYPES:
                ct = "concept"
            lang = str(orig.get("language") or inferred_lang).strip().lower()
            if ct in LANGUAGE_CHALLENGE_TYPES or is_language_studio:
                lang = "en"
            elif lang not in ("java", "sql", "python", "c", "en", "text"):
                lang = inferred_lang

            raw_fb_idata: dict[str, Any] | None = None
            if ct == "fill_blank":
                alt_fb = (
                    f"Complete the blanks using the grammar and vocabulary of {node_title}: "
                    "___ ___ any new assignments on the platform today, or ___ your study group meet on Fridays?"
                )
                new_q = alt_fb if alt_fb != prev_q else (
                    f"Fill in the blanks ({node_title}): ___ she usually ___ her notes in the library, "
                    "and ___ there some examples in the book?"
                )
            elif ct == "translate":
                alt_tr = (
                    f"Write in natural English (1-2 sentences) applying {node_title}: "
                    "'Nosotros estudiamos en la biblioteca cada tarde y hay varios ejercicios prácticos para el examen.'"
                )
                new_q = alt_tr if alt_tr != prev_q else (
                    f"Translate into natural English applying {node_title}: "
                    "'¿Hay algún diccionario en la sala o ella usa su computador para estudiar vocabulario?'"
                )
            elif ct == "speaking_prompt":
                alt_sp = (
                    f"Speaking / Short Answer ({node_title}): Describe your weekly university schedule and "
                    "your favorite place to study in 3-4 complete sentences in English."
                )
                new_q = alt_sp if alt_sp != prev_q else (
                    f"Speaking / Short Answer ({node_title}): What do you usually do on weekends to rest and "
                    "prepare for your classes? Answer in 3-4 sentences in English."
                )
            elif ct == "word_order":
                prev_tiles = (orig.get("interaction_data") or {}).get("tiles") if isinstance(orig.get("interaction_data"), dict) else None
                pick_idx = (idx + 1) % len(_FALLBACK_WORD_ORDER_POOL)
                if prev_tiles and list(prev_tiles) == list(_FALLBACK_WORD_ORDER_POOL[pick_idx]["tiles"]):
                    pick_idx = (pick_idx + 1) % len(_FALLBACK_WORD_ORDER_POOL)
                raw_fb_idata = dict(_FALLBACK_WORD_ORDER_POOL[pick_idx])
                alt_wo = (
                    f"Ordena los bloques en inglés aplicando {node_title} y descarta los distractores sobrantes."
                )
                new_q = alt_wo if alt_wo != prev_q else (
                    f"Construye la oración natural en inglés sobre {node_title} evitando interferencia desde el español."
                )
            elif ct == "categorize":
                prev_cats = (orig.get("interaction_data") or {}).get("categories") if isinstance(orig.get("interaction_data"), dict) else None
                pick_idx = (idx + 1) % len(_FALLBACK_CATEGORIZE_POOL)
                if prev_cats and list(prev_cats) == list(_FALLBACK_CATEGORIZE_POOL[pick_idx]["categories"]):
                    pick_idx = (pick_idx + 1) % len(_FALLBACK_CATEGORIZE_POOL)
                raw_fb_idata = dict(_FALLBACK_CATEGORIZE_POOL[pick_idx])
                alt_cat = (
                    f"Clasifica cada expresión en la categoría gramatical o situacional correcta ({node_title})."
                )
                new_q = alt_cat if alt_cat != prev_q else (
                    f"Asigna los bloques de vocabulario y estructura de {node_title} a su categoría correspondiente."
                )
            elif ct == "find_error":
                prev_sent = (orig.get("interaction_data") or {}).get("sentence") if isinstance(orig.get("interaction_data"), dict) else None
                pick_idx = (idx + 1) % len(_FALLBACK_FIND_ERROR_POOL)
                if prev_sent and str(prev_sent) == str(_FALLBACK_FIND_ERROR_POOL[pick_idx]["sentence"]):
                    pick_idx = (pick_idx + 1) % len(_FALLBACK_FIND_ERROR_POOL)
                raw_fb_idata = dict(_FALLBACK_FIND_ERROR_POOL[pick_idx])
                alt_fe = (
                    f"Detecta si hay un error típico de hispanohablante en la oración de {node_title} y corrígelo."
                )
                new_q = alt_fe if alt_fe != prev_q else (
                    f"Revisa cada palabra de la oración ({node_title}): indica el error y su corrección, o marca 'Sin error'."
                )
            elif ct == "dictation":
                prev_audio = (orig.get("interaction_data") or {}).get("audio_text") if isinstance(orig.get("interaction_data"), dict) else None
                pick_idx = (idx + 1) % len(_FALLBACK_DICTATION_POOL)
                if prev_audio and str(prev_audio) == str(_FALLBACK_DICTATION_POOL[pick_idx]["audio_text"]):
                    pick_idx = (pick_idx + 1) % len(_FALLBACK_DICTATION_POOL)
                raw_fb_idata = dict(_FALLBACK_DICTATION_POOL[pick_idx])
                alt_di = (
                    f"Escucha el dictado en inglés sobre {node_title} y transcribe exactamente lo que oyes."
                )
                new_q = alt_di if alt_di != prev_q else (
                    f"Dictado en inglés ({node_title}): reproduce el audio y escribe la oración completa con precisión."
                )
            else:
                tpl = templates[idx % len(templates)]
                new_q = tpl.format(metaphor=metaphor_hint, node=node_title, course=course_title, focus=focus)
                if new_q == prev_q:
                    new_q = templates[(idx + 1) % len(templates)].format(
                        metaphor=metaphor_hint,
                        node=node_title,
                        course=course_title,
                        focus=focus,
                    )

            prev_starter = str(orig.get("starter_code") or "").strip() or None
            starter = (
                _alternate_starter_code(
                    language=lang,
                    challenge_type=ct,
                    node_title=node_title,
                    prev_starter=prev_starter,
                    idx=idx + 1,
                )
                if ct in ("debug", "implement", "trace")
                else None
            )
            clean_q, clean_starter = sanitize_code_prompt(new_q, starter, lang)
            interaction_data = normalize_language_interaction_data(
                ct,
                raw_fb_idata,
                question=clean_q,
                node_title=node_title,
                idx=idx + 1,
            )
            updated_fallback.append(
                {
                    "id": qid,
                    "question": clean_q,
                    "rubric_points": pts,
                    "challenge_type": ct,
                    "language": lang,
                    "starter_code": clean_starter,
                    "interaction_data": interaction_data,
                }
            )
        return (updated_fallback, "local_fallback")


_DAY_NAMES_ES = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
_MONTH_NAMES_ES = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)


def _format_day_label_es(idx: int, d: date, total_days: int, exam_dt: date) -> str:
    wd = _DAY_NAMES_ES[d.weekday()]
    mon = _MONTH_NAMES_ES[d.month - 1]
    tag = ""
    if idx == 0:
        tag = " (Hoy)"
    elif d == exam_dt:
        tag = " (Examen)"
    elif d == exam_dt - timedelta(days=1) and total_days > 1:
        tag = " (Víspera)"
    return f"Día {idx + 1}{tag} · {wd} {d.day} {mon}"


def _parse_exam_date(raw: str, today: date) -> tuple[date, int]:
    cleaned = raw.strip()[:10]
    try:
        parsed = date.fromisoformat(cleaned)
    except ValueError:
        parsed = today + timedelta(days=5)
    days_left = max(0, (parsed - today).days)
    return parsed, days_left


def _topological_sort_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(n["id"]): n for n in nodes}
    depth_memo: dict[str, int] = {}

    def depth_of(nid: str, seen: set[str]) -> int:
        if nid in depth_memo:
            return depth_memo[nid]
        if nid in seen:
            return 0
        seen = seen | {nid}
        cur = by_id.get(nid)
        parents = [str(p) for p in (cur.get("parent_ids") or []) if str(p) in by_id] if cur else []
        d = 1 + max((depth_of(p, seen) for p in parents), default=-1) if parents else 0
        depth_memo[nid] = d
        return d

    for n in nodes:
        depth_of(str(n["id"]), set())

    idx_map = {str(n["id"]): idx for idx, n in enumerate(nodes)}
    return sorted(nodes, key=lambda n: (depth_memo.get(str(n["id"]), 0), idx_map.get(str(n["id"]), 0)))


def _detect_uncovered_topics(exam_topics: str, nodes: list[dict[str, Any]]) -> list[str]:
    if not exam_topics.strip():
        return []
    corpus = " ".join(
        f"{n.get('title', '')} {n.get('summary', '')} {n.get('block', '')}" for n in nodes
    ).lower()
    raw_lines = [
        line.strip(" -•*\t.:")
        for line in re.split(r"[\n;]+", exam_topics)
        if line.strip()
    ]
    ignore_headers = {
        "grammar",
        "vocabulary",
        "vocabulario",
        "gramatica",
        "gramática",
        "temario",
        "contenidos",
        "contents",
        "final exam contents",
        "list of students",
        "lista",
    }
    uncovered: list[str] = []
    for line in raw_lines:
        low = line.lower()
        if len(line) < 3 or low in ignore_headers:
            continue
        if any(skip in low for skip in ("clave ", "sala:", "date:", "list of students", "final exam")):
            continue
        tokens = [t for t in re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ0-9]{3,}", low)]
        if not tokens:
            continue
        matched = sum(1 for t in tokens if t in corpus or t[:4] in corpus)
        if matched / len(tokens) < 0.4:
            uncovered.append(line)
    return uncovered[:12]


def _build_fallback_exam_route(
    *,
    course_title: str,
    nodes: list[dict[str, Any]],
    exam_dt: date,
    today: date,
    days_left: int,
    hours_per_day: float,
    goal: str,
    exam_topics: str,
) -> dict[str, Any]:
    recommended_mode = "urgency" if days_left <= 10 else "semester"
    study_days = 1 if days_left == 0 else min(max(1, days_left), 10)
    daily_minutes = max(45, round(hours_per_day * 60))

    theory_nodes = _topological_sort_nodes([n for n in nodes if n.get("branch") != "practice"])
    practice_nodes = _topological_sort_nodes([n for n in nodes if n.get("branch") == "practice"])

    pending_theory = [n for n in theory_nodes if int(n.get("mastery_level") or 0) < 3]
    pending_practice = [n for n in practice_nodes if int(n.get("mastery_level") or 0) < 3]

    # Construir cola ordenada: teoría pendiente (0/3 primero), luego repaso 2/3-3/3, luego práctica/simulacro
    queue: list[dict[str, Any]] = []
    for n in pending_theory:
        lvl = int(n.get("mastery_level") or 0)
        queue.append(
            {
                "node_id": str(n["id"]),
                "node_title": str(n["title"]),
                "branch": "theory",
                "action": "study_and_eval" if lvl == 0 else "spaced_review",
                "target_mastery": min(3, lvl + 1),
                "estimated_minutes": 40 if lvl == 0 else 25,
                "reason": (
                    "Base obligatoria pendiente (0/3): entiende la historia y logra >= 7/10 a ciegas."
                    if lvl == 0
                    else f"Consolidación espaciada desde {lvl}/3 hacia {min(3, lvl + 1)}/3."
                ),
            }
        )

    for n in pending_practice:
        lvl = int(n.get("mastery_level") or 0)
        queue.append(
            {
                "node_id": str(n["id"]),
                "node_title": str(n["title"]),
                "branch": "practice",
                "action": "practice_exam",
                "target_mastery": min(3, max(1, lvl + 1)),
                "estimated_minutes": 45,
                "reason": "Simulacro práctico/examen para validar aplicación sin apuntes.",
            }
        )

    # Si ya está casi todo en 3/3 o hay días extra, agregar ronda de repaso de los de menor best_score
    if len(queue) < study_days * 2 and nodes:
        weakest = sorted(
            nodes,
            key=lambda n: (int(n.get("mastery_level") or 0), float(n.get("best_score") or 0.0)),
        )[: max(3, study_days)]
        for n in weakest:
            queue.append(
                {
                    "node_id": str(n["id"]),
                    "node_title": str(n["title"]),
                    "branch": str(n.get("branch") or "theory"),
                    "action": "spaced_review",
                    "target_mastery": 3,
                    "estimated_minutes": 25,
                    "reason": "Repaso de consolidación en orden mezclado para fijar retención antes del examen.",
                }
            )

    days: list[dict[str, Any]] = []
    if study_days == 1:
        selected_steps: list[dict[str, Any]] = []
        acc = 0
        for step in queue:
            if acc + step["estimated_minutes"] <= daily_minutes + 30 or not selected_steps:
                selected_steps.append(step)
                acc += step["estimated_minutes"]
            if len(selected_steps) >= 6:
                break
        d0 = today
        days.append(
            {
                "day_label": _format_day_label_es(0, d0, 1, exam_dt),
                "date": d0.isoformat(),
                "focus": "Bloque intensivo de máxima prioridad y simulacro final",
                "steps": selected_steps,
            }
        )
    else:
        buckets: list[list[dict[str, Any]]] = [[] for _ in range(study_days)]
        # Reservar el último día principalmente para práctica / simulacros y repaso final
        practice_steps = [s for s in queue if s["action"] == "practice_exam"]
        theory_steps = [s for s in queue if s["action"] != "practice_exam"]
        theory_span = max(1, study_days - (1 if practice_steps and study_days >= 2 else 0))

        for i, step in enumerate(theory_steps):
            day_idx = min(theory_span - 1, (i * theory_span) // max(1, len(theory_steps)))
            buckets[day_idx].append(step)

        for i, step in enumerate(practice_steps):
            day_idx = study_days - 1 if study_days >= 2 else 0
            if len(buckets[day_idx]) >= 4 and study_days >= 3:
                day_idx = study_days - 2
            buckets[day_idx].append(step)

        # Garantizar que ningún día quede vacío
        for day_idx in range(study_days):
            if not buckets[day_idx] and nodes:
                ref = nodes[day_idx % len(nodes)]
                buckets[day_idx].append(
                    {
                        "node_id": str(ref["id"]),
                        "node_title": str(ref["title"]),
                        "branch": str(ref.get("branch") or "theory"),
                        "action": "spaced_review",
                        "target_mastery": 3,
                        "estimated_minutes": 30,
                        "reason": "Repaso espaciado y verificación a ciegas con nuevas preguntas.",
                    }
                )

        for day_idx in range(study_days):
            cur_date = today + timedelta(days=day_idx)
            steps = buckets[day_idx][:6]
            if day_idx == study_days - 1:
                focus = "Simulacros prácticos y repaso final sin apuntes"
            elif day_idx == 0:
                focus = "Bases fundamentales y primeros nodos en 1/3"
            else:
                focus = "Avance troncal + consolidación espaciada (2/3 -> 3/3)"
            days.append(
                {
                    "day_label": _format_day_label_es(day_idx, cur_date, study_days, exam_dt),
                    "date": cur_date.isoformat(),
                    "focus": focus,
                    "steps": steps,
                }
            )

    goal_note = f" Objetivo declarado: {goal.strip()}." if goal.strip() else ""
    summary = (
        f"Plan de {study_days} {'día' if study_days == 1 else 'días'} para {course_title} "
        f"(faltan {days_left} {'día' if days_left == 1 else 'días'}, ~{hours_per_day:g} h/día). "
        f"Prioriza cerrar nodos base 0/3 en orden de prerrequisitos, consolidar 2/3–3/3 en bloques separados "
        f"y rematar con simulacros prácticos.{goal_note}"
    )
    return {
        "strategy_summary": summary,
        "recommended_cooldown_mode": recommended_mode,
        "days": days,
        "uncovered_topics": _detect_uncovered_topics(exam_topics, nodes),
    }


def generate_exam_route_with_ai(
    *,
    course_title: str,
    engine_type: str,
    nodes: list[dict[str, Any]],
    exam_date: str,
    hours_per_day: float = 3.0,
    goal: str = "",
    exam_topics: str = "",
    preferred_provider: str = "auto",
    today: date | None = None,
) -> tuple[dict[str, Any], date, int, str]:
    """Genera una ruta realista día a día para preparar un examen sobre el árbol del ramo."""
    today_dt = today or date.today()
    exam_dt, days_left = _parse_exam_date(exam_date, today_dt)
    study_days = 1 if days_left == 0 else min(max(1, days_left), 10)
    recommended_mode = "urgency" if days_left <= 10 else "semester"

    valid_by_id = {str(n["id"]): n for n in nodes}
    valid_by_title = {str(n["title"]).strip().lower(): n for n in nodes}

    compact_nodes = [
        {
            "id": str(n["id"]),
            "title": str(n["title"]),
            "block": str(n.get("block") or ""),
            "branch": str(n.get("branch") or "theory"),
            "parent_ids": list(n.get("parent_ids") or []),
            "mastery_level": int(n.get("mastery_level") or 0),
            "best_score": float(n.get("best_score") or 0.0),
            "summary": str(n.get("summary") or "")[:180],
        }
        for n in _topological_sort_nodes(nodes)
    ]

    day_slots = [
        {
            "index": idx,
            "date": (today_dt + timedelta(days=idx)).isoformat(),
            "day_label": _format_day_label_es(idx, today_dt + timedelta(days=idx), study_days, exam_dt),
        }
        for idx in range(study_days)
    ]

    try:
        system_prompt = (
            "Eres un estratega académico de Brotal (método 5R + sistema 7/10 y retención espaciada 0/3 -> 3/3).\n"
            "Tu trabajo es diseñar una RUTA REALISTA día a día para preparar un examen con los nodos EXACTOS del árbol.\n"
            "Reglas estrictas:\n"
            "- Responde SOLO JSON válido con claves: strategy_summary (string conciso 2-3 oraciones en español), "
            "recommended_cooldown_mode ('urgency' si faltan <= 10 días, si no 'semester'), "
            "days (lista de objetos {day_label, date, focus, steps}), "
            "uncovered_topics (lista de strings con temas del temario del examen que NO estén cubiertos por los nodos actuales; lista vacía si no se dio temario o todo está cubierto).\n"
            "- Cada step debe tener: node_id (DEBE existir en nodes o null solo si es práctica externa puntual), "
            "node_title, branch ('theory'|'practice'|'review'), "
            "action ('study_and_eval' | 'spaced_review' | 'practice_exam' | 'custom'), "
            "target_mastery (1, 2 o 3), estimated_minutes (15 a 90), reason (1 línea concreta de por qué ahora).\n"
            "- Respeta los prerrequisitos (parent_ids) y prioriza nodos en 0/3 y 1/3 antes de repetir nodos ya en 3/3.\n"
            "- Programa repasos espaciados en días posteriores para subir nodos críticos de 1/3 -> 2/3 -> 3/3, y deja los nodos 'practice' (simulacros) para la recta final.\n"
            "- Respeta las horas/día disponibles (~hours_per_day * 60 minutos por día) y usa EXACTAMENTE los day_slots entregados."
        )
        user_payload = {
            "course_title": course_title,
            "engine_type": engine_type,
            "today": today_dt.isoformat(),
            "exam_date": exam_dt.isoformat(),
            "days_left": days_left,
            "hours_per_day": hours_per_day,
            "goal": goal.strip(),
            "exam_topics": exam_topics.strip()[:3000],
            "day_slots": day_slots,
            "nodes": compact_nodes,
        }
        comp = complete_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            preferred_provider=preferred_provider,
            json_mode=True,
            temperature=0.35,
            max_tokens=4096,
        )
        parsed = extract_json_object(comp.text)
        raw_days = parsed.get("days")
        if not isinstance(raw_days, list) or not raw_days:
            raise ValueError("Ruta sin días válidos")

        clean_days: list[dict[str, Any]] = []
        for idx, raw_day in enumerate(raw_days[:12]):
            if not isinstance(raw_day, dict):
                continue
            slot = day_slots[idx] if idx < len(day_slots) else None
            d_date = str(raw_day.get("date") or (slot["date"] if slot else today_dt.isoformat()))[:10]
            d_label = str(raw_day.get("day_label") or (slot["day_label"] if slot else f"Día {idx + 1}")).strip()
            d_focus = str(raw_day.get("focus") or "Bloque de estudio dirigido").strip()
            raw_steps = raw_day.get("steps")
            clean_steps: list[dict[str, Any]] = []
            if isinstance(raw_steps, list):
                for st in raw_steps[:8]:
                    if not isinstance(st, dict):
                        continue
                    cand_id = str(st.get("node_id") or "").strip() or None
                    cand_title = str(st.get("node_title") or "").strip()
                    matched_node = valid_by_id.get(cand_id) if cand_id else None
                    if matched_node is None and cand_title:
                        matched_node = valid_by_title.get(cand_title.lower())
                    if matched_node is not None:
                        final_id: str | None = str(matched_node["id"])
                        final_title = str(matched_node["title"])
                        final_branch = str(matched_node.get("branch") or "theory")
                    else:
                        if not cand_title:
                            continue
                        final_id = None
                        final_title = cand_title
                        final_branch = str(st.get("branch") or "review")

                    raw_action = str(st.get("action") or "study_and_eval").strip().lower()
                    if raw_action not in ("study_and_eval", "spaced_review", "practice_exam", "custom"):
                        raw_action = "practice_exam" if final_branch == "practice" else "study_and_eval"
                    try:
                        t_mastery = max(1, min(3, int(st.get("target_mastery") or 1)))
                    except (TypeError, ValueError):
                        t_mastery = 1
                    try:
                        est_min = max(10, min(180, int(st.get("estimated_minutes") or 35)))
                    except (TypeError, ValueError):
                        est_min = 35
                    reason = str(st.get("reason") or "Paso clave de la ruta de examen.").strip()
                    clean_steps.append(
                        {
                            "node_id": final_id,
                            "node_title": final_title,
                            "branch": final_branch,
                            "action": raw_action,
                            "target_mastery": t_mastery,
                            "estimated_minutes": est_min,
                            "reason": reason,
                        }
                    )
            if clean_steps:
                clean_days.append(
                    {
                        "day_label": d_label,
                        "date": d_date,
                        "focus": d_focus,
                        "steps": clean_steps,
                    }
                )

        if not clean_days:
            raise ValueError("La IA no devolvió pasos válidos")

        raw_uncovered = parsed.get("uncovered_topics")
        uncovered = (
            [str(x).strip() for x in raw_uncovered if str(x).strip()][:12]
            if isinstance(raw_uncovered, list)
            else []
        )
        raw_mode = str(parsed.get("recommended_cooldown_mode") or recommended_mode).strip().lower()
        final_mode = "urgency" if raw_mode == "urgency" else "semester"
        summary = str(parsed.get("strategy_summary") or "").strip()
        if not summary:
            summary = (
                f"Ruta de {len(clean_days)} días para {course_title} "
                f"(faltan {days_left} días, {hours_per_day:g} h/día)."
            )

        return (
            {
                "strategy_summary": summary,
                "recommended_cooldown_mode": final_mode,
                "days": clean_days,
                "uncovered_topics": uncovered,
            },
            exam_dt,
            days_left,
            comp.provider,
        )
    except (AiProviderError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        fallback = _build_fallback_exam_route(
            course_title=course_title,
            nodes=nodes,
            exam_dt=exam_dt,
            today=today_dt,
            days_left=days_left,
            hours_per_day=hours_per_day,
            goal=goal,
            exam_topics=exam_topics,
        )
        return (fallback, exam_dt, days_left, "local_fallback")


# ---------------------------------------------------------------------------
# Animaciones explicativas auto-adaptativas por nodo (v1.2.2)
# ---------------------------------------------------------------------------

_STORYBOARD_VARIANTS = (
    "execution_trace",
    "oop_dispatch",
    "error_contrast",
    "data_structure",
    "sql_pipeline",
)
_STORYBOARD_LANGUAGES = ("java", "python", "c", "sql")
_SQL_PIPELINE_STAGES = ["FROM/JOIN", "WHERE", "GROUP BY", "HAVING", "SELECT", "ORDER BY"]


def _strip_accents_lower(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in norm if not unicodedata.combining(ch)).lower()


def _detect_storyboard_language_and_variant(
    course_title: str,
    node_title: str,
    node_summary: str,
    story_script: str,
) -> tuple[str, str]:
    """Detecta de forma heurística determinista (language, variant) para un nodo."""
    raw_node = f"{node_title or ''}\n{node_summary or ''}"
    raw_story = story_script or ""

    norm_course = _strip_accents_lower(course_title)
    norm_node = _strip_accents_lower(raw_node)
    norm_story = _strip_accents_lower(raw_story)
    norm_full = f"{norm_course}\n{norm_node}\n{norm_story}"

    fence_langs = [
        m.group(1).lower()
        for m in re.finditer(r"```\s*(java|python|py|c|sql)\b", raw_story, flags=re.IGNORECASE)
    ]

    sql_clause_patterns = (
        r"\bSELECT\b",
        r"\bFROM\b",
        r"\bWHERE\b",
        r"\bGROUP\s+BY\b",
        r"\bHAVING\b",
        r"\bINNER\s+JOIN\b",
        r"\bLEFT\s+JOIN\b",
        r"\bORDER\s+BY\b",
    )
    sql_clause_hits = sum(
        1 for pat in sql_clause_patterns if re.search(pat, raw_node + "\n" + raw_story, flags=re.IGNORECASE)
    )
    has_select_from = bool(
        re.search(r"\bSELECT\b[\s\S]{1,360}\bFROM\b", raw_node + "\n" + raw_story, flags=re.IGNORECASE)
    )
    has_sql_heavy_clause = bool(
        re.search(
            r"\b(?:GROUP\s+BY|HAVING|INNER\s+JOIN|LEFT\s+JOIN|ORDER\s+BY)\b",
            raw_node + "\n" + raw_story,
            flags=re.IGNORECASE,
        )
    )

    language = "java"
    if (
        "sql" in fence_langs
        or has_select_from
        or sql_clause_hits >= 3
        or (has_sql_heavy_clause and sql_clause_hits >= 2)
        or (re.search(r"\bsql\b", norm_full) and (sql_clause_hits >= 1 or "consulta" in norm_full))
    ):
        language = "sql"
    elif (
        "python" in fence_langs
        or "py" in fence_langs
        or re.search(r"\bpython\b", norm_full)
        or re.search(r"\bdef\s+[A-Za-z_]\w*\s*\([^)]*\)\s*:", raw_story)
    ):
        language = "python"
    elif (
        "c" in fence_langs
        or re.search(r"#include\s*<", raw_story)
        or re.search(r"\b(?:malloc|calloc|free|printf|scanf|sizeof)\s*\(", raw_story)
        or re.search(r"\blenguaje\s+c\b|\ben\s+c\b|\bpunteros\s+en\s+c\b", norm_full)
    ):
        language = "c"
    elif "java" in fence_langs:
        language = "java"

    # 1. SQL Pipeline
    if language == "sql" or has_select_from or sql_clause_hits >= 3 or (has_sql_heavy_clause and sql_clause_hits >= 2):
        return ("sql", "sql_pipeline")

    def _weighted_hits(
        norm_pats: tuple[str, ...],
        raw_pats: tuple[str, ...] = (),
    ) -> tuple[int, int]:
        node_hits = 0
        story_hits = 0
        for p in norm_pats:
            if re.search(p, norm_node):
                node_hits += 1
            if re.search(p, norm_story):
                story_hits += 1
        for p in raw_pats:
            if re.search(p, raw_node):
                node_hits += 1
            if re.search(p, raw_story):
                story_hits += 1
        return (node_hits, node_hits * 4 + story_hits)

    oop_norm_pats = (
        r"\bextends\b",
        r"\bimplements\b",
        r"\bsuper\s*\(",
        r"\bsuper\.",
        r"\bpolimorfismo\b",
        r"\bherencia\b",
        r"\bsobrescritura\b",
        r"despacho\s+dinamico",
        r"clase(?:s)?\s+abstracta(?:s)?",
        r"\binterfaz\b|\binterfaces\b",
        r"tipo\s+estatico",
        r"tipo\s+dinamico",
    )
    oop_raw_pats = (r"@Override\b",)

    err_norm_pats = (
        r"\btry\b",
        r"\bcatch\b",
        r"\bthrow\b",
        r"\bthrows\b",
        r"\bexcepcion(?:es)?\b",
        r"stack\s+unwinding",
        r"\bbug(?:s)?\b",
        r"segmentation\s+fault",
        r"error(?:es)?\s+comun(?:es)?",
        r"nullpointer",
        r"indexoutofbounds",
        r"(?:comparacion\s+de\s+strings|==\s*vs\.?\s*equals)[\s\S]{0,90}(?:fallo|bug|error|trampa|null)",
    )
    err_raw_pats = (r"\b[A-Za-z]*Exception\b",)

    ds_norm_pats = (
        r"\barraylist\b",
        r"\bhashmap\b",
        r"\blinkedlist\b",
        r"\barreglo(?:s)?\b",
        r"\barray(?:s)?\b",
        r"lista(?:s)?\s+enlazada(?:s)?",
        r"\bpila(?:s)?\b",
        r"\bcola(?:s)?\b",
        r"\bmatriz\b|\bmatrices\b",
        r"\bbucket(?:s)?\b",
        r"\bpuntero(?:s)?\b",
        r"\bindice(?:s)?\b",
        r"\bdiccionario(?:s)?\b",
        r"estructura(?:s)?\s+de\s+datos|nodos\s+enlazados",
    )

    oop_node_hits, oop_score = _weighted_hits(oop_norm_pats, oop_raw_pats)
    err_node_hits, err_score = _weighted_hits(err_norm_pats, err_raw_pats)
    ds_node_hits, ds_score = _weighted_hits(ds_norm_pats)

    if max(oop_score, err_score, ds_score) == 0:
        return (language, "execution_trace")

    # Desempate explícito entre OOP y Error Contrast según foco del nodo
    if err_node_hits > 0 and err_node_hits >= oop_node_hits and err_score >= ds_score:
        return (language, "error_contrast")
    if oop_node_hits > 0 and oop_node_hits > err_node_hits and oop_score >= ds_score:
        return (language, "oop_dispatch")
    if ds_node_hits > 0 and ds_score > oop_score and ds_score > err_score:
        return (language, "data_structure")

    if oop_score >= err_score and oop_score >= ds_score and oop_score > 0:
        if err_score > oop_score:
            return (language, "error_contrast")
        return (language, "oop_dispatch")
    if err_score >= oop_score and err_score >= ds_score and err_score > 0:
        return (language, "error_contrast")
    if ds_score > 0:
        return (language, "data_structure")

    return (language, "execution_trace")


def _clean_micro_caption(raw: Any, fallback: str) -> str:
    text = str(raw or "").strip()
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    words = [w for w in text.split(" ") if w]
    if not words:
        words = [w for w in fallback.split(" ") if w]
    if len(words) > 12:
        words = words[:12]
        words[-1] = words[-1].rstrip(",;:")
        if words[-1] and words[-1][-1] not in ".!?":
            words[-1] = words[-1] + "."
    return " ".join(words[:12])


def _clean_storyboard_code(raw_code: Any, language: str, max_lines: int = 22) -> str:
    s = _clean_fenced_solution(raw_code)
    if not s and isinstance(raw_code, str):
        s = raw_code.strip()
    if not s:
        return ""
    formatted = format_multiline_starter_code(s, language) or s
    lines = [ln.rstrip() for ln in formatted.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    return "\n".join(lines)


def _extract_story_code_block(story_script: str, language: str) -> str | None:
    if not story_script:
        return None
    m = re.search(r"```(?:[A-Za-z0-9_+-]*)?[ \t]*\n([\s\S]*?)```", story_script)
    if not m:
        return None
    cleaned = _clean_storyboard_code(m.group(1), language, max_lines=22)
    line_count = len(cleaned.splitlines())
    if 6 <= line_count <= 22:
        return cleaned
    return None


def _compute_sentence_indices(
    raw_indices: list[int | None],
    story_script: str,
    step_count: int,
) -> list[int]:
    sentences = split_story_sentences(story_script or "")
    num_sentences = len(sentences)
    if step_count <= 0:
        return []
    if num_sentences <= 0:
        return [0 for _ in range(step_count)]

    out: list[int] = []
    prev = 0
    for idx in range(step_count):
        prop = min(num_sentences - 1, (idx * num_sentences) // max(1, step_count))
        cand = raw_indices[idx] if idx < len(raw_indices) else None
        if isinstance(cand, int) and 0 <= cand < num_sentences and cand >= prev:
            chosen = cand
        else:
            chosen = max(prev, prop)
        prev = chosen
        out.append(chosen)
    return out


def _sanitize_execution_trace_state(raw_state: Any, step_idx: int, caption: str) -> dict[str, Any]:
    st = raw_state if isinstance(raw_state, dict) else {}
    frames_out: list[dict[str, Any]] = []
    raw_frames = st.get("frames")
    if isinstance(raw_frames, list):
        for f_idx, fr in enumerate(raw_frames[:6]):
            if not isinstance(fr, dict):
                continue
            vars_out: list[dict[str, Any]] = []
            raw_vars = fr.get("vars")
            if isinstance(raw_vars, list):
                for vr in raw_vars[:10]:
                    if not isinstance(vr, dict):
                        continue
                    ref_raw = vr.get("ref_id")
                    vars_out.append(
                        {
                            "name": str(vr.get("name") or "var"),
                            "value": str(vr.get("value") if vr.get("value") is not None else ""),
                            "type": str(vr.get("type") or "int"),
                            "changed": bool(vr.get("changed", False)),
                            "ref_id": str(ref_raw) if ref_raw else None,
                        }
                    )
            frames_out.append(
                {
                    "name": str(fr.get("name") or ("main" if f_idx == 0 else f"frame_{f_idx}")),
                    "active": bool(fr.get("active", f_idx == len(raw_frames) - 1)),
                    "vars": vars_out,
                }
            )
    if not frames_out:
        frames_out = [
            {
                "name": "main",
                "active": True,
                "vars": [{"name": "paso", "value": str(step_idx + 1), "type": "int", "changed": True, "ref_id": None}],
            }
        ]

    heap_out: list[dict[str, Any]] = []
    raw_heap = st.get("heap")
    if isinstance(raw_heap, list):
        for h_idx, hp in enumerate(raw_heap[:6]):
            if not isinstance(hp, dict):
                continue
            fields_out: list[dict[str, Any]] = []
            raw_fields = hp.get("fields")
            if isinstance(raw_fields, list):
                for fld in raw_fields[:8]:
                    if not isinstance(fld, dict):
                        continue
                    fields_out.append(
                        {
                            "name": str(fld.get("name") or "campo"),
                            "value": str(fld.get("value") if fld.get("value") is not None else ""),
                            "changed": bool(fld.get("changed", False)),
                        }
                    )
            heap_out.append(
                {
                    "id": str(hp.get("id") or f"obj{h_idx + 1}"),
                    "class_name": str(hp.get("class_name") or "Objeto"),
                    "address": str(hp.get("address") or f"@0x{10 + h_idx:02X}"),
                    "fields": fields_out,
                }
            )

    raw_stdout = st.get("stdout")
    stdout_out = [str(x) for x in raw_stdout[:8]] if isinstance(raw_stdout, list) else []
    delta_out = str(st.get("delta") or caption).strip() or f"Paso {step_idx + 1}"

    return {
        "frames": frames_out,
        "heap": heap_out,
        "stdout": stdout_out,
        "delta": delta_out,
    }


def _sanitize_oop_dispatch_state(raw_state: Any) -> dict[str, Any]:
    st = raw_state if isinstance(raw_state, dict) else {}
    classes_out: list[dict[str, Any]] = []
    raw_classes = st.get("classes")
    if isinstance(raw_classes, list):
        for cl in raw_classes[:6]:
            if not isinstance(cl, dict):
                continue
            parent_raw = cl.get("parent")
            methods_raw = cl.get("methods")
            classes_out.append(
                {
                    "name": str(cl.get("name") or "Base"),
                    "parent": str(parent_raw) if parent_raw else None,
                    "methods": [str(m) for m in methods_raw[:6]] if isinstance(methods_raw, list) else [],
                    "active": bool(cl.get("active", False)),
                }
            )
    if not classes_out:
        classes_out = [
            {"name": "Base", "parent": None, "methods": ["ejecutar()"], "active": False},
            {"name": "Subclase", "parent": "Base", "methods": ["@Override ejecutar()"], "active": True},
        ]

    refs_out: list[dict[str, str]] = []
    raw_refs = st.get("references")
    if isinstance(raw_refs, list):
        for rf in raw_refs[:6]:
            if not isinstance(rf, dict):
                continue
            refs_out.append(
                {
                    "var_name": str(rf.get("var_name") or "ref"),
                    "static_type": str(rf.get("static_type") or classes_out[0]["name"]),
                    "dynamic_type": str(rf.get("dynamic_type") or classes_out[-1]["name"]),
                    "heap_id": str(rf.get("heap_id") or "obj1"),
                }
            )

    heap_out: list[dict[str, Any]] = []
    raw_heap = st.get("heap_objects")
    if isinstance(raw_heap, list):
        for h_idx, hp in enumerate(raw_heap[:6]):
            if not isinstance(hp, dict):
                continue
            fields_out: list[dict[str, str]] = []
            raw_fields = hp.get("fields")
            if isinstance(raw_fields, list):
                for fld in raw_fields[:8]:
                    if isinstance(fld, dict):
                        fields_out.append(
                            {
                                "name": str(fld.get("name") or "estado"),
                                "value": str(fld.get("value") if fld.get("value") is not None else ""),
                            }
                        )
            heap_out.append(
                {
                    "id": str(hp.get("id") or f"obj{h_idx + 1}"),
                    "class_name": str(hp.get("class_name") or classes_out[-1]["name"]),
                    "fields": fields_out,
                }
            )

    raw_disp = st.get("dispatch") if isinstance(st.get("dispatch"), dict) else {}
    raw_lookup = raw_disp.get("lookup_path")
    lookup_out = (
        [str(x) for x in raw_lookup[:6]]
        if isinstance(raw_lookup, list) and raw_lookup
        else [classes_out[-1]["name"]]
    )
    dispatch_out = {
        "call_expr": str(raw_disp.get("call_expr") or "ref.ejecutar()"),
        "static_check": str(raw_disp.get("static_check") or f"{classes_out[0]['name']}.ejecutar() verificado"),
        "lookup_path": lookup_out,
        "resolved_class": str(raw_disp.get("resolved_class") or lookup_out[-1]),
        "resolved_method": str(raw_disp.get("resolved_method") or "ejecutar()"),
        "via_super": bool(raw_disp.get("via_super", False)),
    }

    return {
        "classes": classes_out,
        "references": refs_out,
        "heap_objects": heap_out,
        "dispatch": dispatch_out,
    }


def _sanitize_error_contrast_state(raw_state: Any, max_line: int) -> dict[str, Any]:
    st = raw_state if isinstance(raw_state, dict) else {}
    valid_phases = ("running", "exception_thrown", "stack_unwinding", "caught", "contrast_fix")
    raw_phase = str(st.get("phase") or "running").strip().lower()
    phase = raw_phase if raw_phase in valid_phases else "running"

    raw_view = str(st.get("code_view") or "").strip().lower()
    if raw_view in ("broken", "fixed"):
        code_view = raw_view
    else:
        code_view = "fixed" if phase == "contrast_fix" else "broken"

    exc_out: dict[str, Any] | None = None
    raw_exc = st.get("exception")
    if isinstance(raw_exc, dict) and (raw_exc.get("type") or raw_exc.get("message")):
        try:
            exc_line = max(1, min(max_line, int(raw_exc.get("line") or 1)))
        except (TypeError, ValueError):
            exc_line = 1
        exc_out = {
            "type": str(raw_exc.get("type") or "RuntimeException"),
            "message": str(raw_exc.get("message") or "Operación inválida en tiempo de ejecución"),
            "line": exc_line,
        }

    valid_statuses = ("active", "crashed", "unwinding", "catching", "ok")
    stack_out: list[dict[str, Any]] = []
    raw_stack = st.get("call_stack")
    if isinstance(raw_stack, list):
        for fr in raw_stack[:8]:
            if not isinstance(fr, dict):
                continue
            raw_st = str(fr.get("status") or "active").strip().lower()
            st_val = raw_st if raw_st in valid_statuses else "active"
            try:
                fr_line = max(1, min(max_line, int(fr.get("line") or 1)))
            except (TypeError, ValueError):
                fr_line = 1
            stack_out.append(
                {
                    "frame": str(fr.get("frame") or "main()"),
                    "status": st_val,
                    "line": fr_line,
                }
            )
    if not stack_out:
        default_status = "ok" if code_view == "fixed" else ("crashed" if phase == "exception_thrown" else "active")
        stack_out = [{"frame": "main()", "status": default_status, "line": 1}]

    raw_contrast = st.get("contrast") if isinstance(st.get("contrast"), dict) else {}
    contrast_out = {
        "bug_cause": str(raw_contrast.get("bug_cause") or "Falta validación previa antes de desreferenciar u operar."),
        "broken_line": str(raw_contrast.get("broken_line") or "return texto.trim().toUpperCase();"),
        "fixed_line": str(raw_contrast.get("fixed_line") or "if (texto == null) return \"\";"),
        "fix_explanation": str(
            raw_contrast.get("fix_explanation")
            or "La guarda explícita evita disparar la excepción y mantiene el invariante seguro."
        ),
    }

    return {
        "phase": phase,
        "code_view": code_view,
        "exception": exc_out,
        "call_stack": stack_out,
        "contrast": contrast_out,
    }


def _sanitize_data_structure_state(raw_state: Any, caption: str) -> dict[str, Any]:
    st = raw_state if isinstance(raw_state, dict) else {}
    valid_types = ("array", "arraylist", "hashmap", "linkedlist")
    raw_type = str(st.get("structure_type") or "arraylist").strip().lower()
    structure_type = raw_type if raw_type in valid_types else "arraylist"

    cells_out: list[dict[str, Any]] = []
    valid_cell_states = ("normal", "active", "changed", "empty")
    raw_cells = st.get("cells")
    if isinstance(raw_cells, list):
        for c_idx, cell in enumerate(raw_cells[:12]):
            if not isinstance(cell, dict):
                continue
            try:
                idx_val = int(cell.get("index", c_idx))
            except (TypeError, ValueError):
                idx_val = c_idx
            c_state = str(cell.get("state") or "normal").strip().lower()
            if c_state not in valid_cell_states:
                c_state = "normal"
            nxt = cell.get("next_index")
            try:
                nxt_val: int | None = int(nxt) if nxt is not None else None
            except (TypeError, ValueError):
                nxt_val = None
            cells_out.append(
                {
                    "index": idx_val,
                    "value": str(cell.get("value") if cell.get("value") is not None else ""),
                    "state": c_state,
                    "next_index": nxt_val,
                }
            )

    pointers_out: list[dict[str, Any]] = []
    raw_ptrs = st.get("pointers")
    if isinstance(raw_ptrs, list):
        for ptr in raw_ptrs[:6]:
            if not isinstance(ptr, dict):
                continue
            try:
                p_idx = int(ptr.get("index") or 0)
            except (TypeError, ValueError):
                p_idx = 0
            pointers_out.append({"name": str(ptr.get("name") or "i"), "index": p_idx})

    buckets_out: list[dict[str, Any]] = []
    raw_buckets = st.get("buckets")
    if isinstance(raw_buckets, list):
        for b_idx, bk in enumerate(raw_buckets[:8]):
            if not isinstance(bk, dict):
                continue
            try:
                b_num = int(bk.get("bucket", b_idx))
            except (TypeError, ValueError):
                b_num = b_idx
            entries_out: list[dict[str, Any]] = []
            raw_entries = bk.get("entries")
            if isinstance(raw_entries, list):
                for ent in raw_entries[:6]:
                    if not isinstance(ent, dict):
                        continue
                    entries_out.append(
                        {
                            "key": str(ent.get("key") or ""),
                            "value": str(ent.get("value") or ""),
                            "hash_formula": str(ent.get("hash_formula") or f"hash % 4 = {b_num}"),
                            "active": bool(ent.get("active", False)),
                        }
                    )
            buckets_out.append({"bucket": b_num, "entries": entries_out})

    try:
        size_val = max(0, int(st.get("size", len([c for c in cells_out if c["state"] != "empty"]))))
    except (TypeError, ValueError):
        size_val = 0
    try:
        cap_val = max(size_val, int(st.get("capacity", max(4, len(cells_out) or len(buckets_out) or 4))))
    except (TypeError, ValueError):
        cap_val = max(4, size_val)

    return {
        "structure_type": structure_type,
        "label": str(st.get("label") or structure_type),
        "size": size_val,
        "capacity": cap_val,
        "cells": cells_out,
        "pointers": pointers_out,
        "buckets": buckets_out,
        "operation": str(st.get("operation") or caption),
    }


def _sanitize_sql_pipeline_state(raw_state: Any, caption: str) -> dict[str, Any]:
    st = raw_state if isinstance(raw_state, dict) else {}
    valid_clauses = ("FROM", "JOIN", "WHERE", "GROUP BY", "HAVING", "SELECT", "ORDER BY")
    raw_clause = str(st.get("active_clause") or "FROM").strip().upper()
    if raw_clause in ("INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "FROM/JOIN"):
        raw_clause = "JOIN" if "JOIN" in raw_clause and raw_clause != "FROM/JOIN" else "FROM"
    active_clause = raw_clause if raw_clause in valid_clauses else "FROM"

    raw_stages = st.get("pipeline_stages")
    stages_out = (
        [str(x) for x in raw_stages[:8] if str(x).strip()]
        if isinstance(raw_stages, list) and raw_stages
        else list(_SQL_PIPELINE_STAGES)
    )

    raw_cols = st.get("columns")
    cols_out = [str(c) for c in raw_cols[:8]] if isinstance(raw_cols, list) and raw_cols else ["id", "valor"]

    valid_row_statuses = ("kept", "filtered_out", "grouped", "projected")
    rows_out: list[dict[str, Any]] = []
    raw_rows = st.get("rows")
    if isinstance(raw_rows, list):
        for rw in raw_rows[:12]:
            if not isinstance(rw, dict):
                continue
            raw_vals = rw.get("values")
            vals = [str(v) for v in raw_vals[: len(cols_out)]] if isinstance(raw_vals, list) else []
            while len(vals) < len(cols_out):
                vals.append("")
            r_status = str(rw.get("status") or "kept").strip().lower()
            if r_status not in valid_row_statuses:
                r_status = "kept"
            gk = rw.get("group_key")
            rows_out.append(
                {
                    "values": vals,
                    "status": r_status,
                    "group_key": str(gk) if gk is not None and str(gk) != "" else None,
                }
            )

    return {
        "active_clause": active_clause,
        "pipeline_stages": stages_out,
        "clause_sql": str(st.get("clause_sql") or active_clause),
        "columns": cols_out,
        "rows": rows_out,
        "note": str(st.get("note") or caption),
    }


def _sanitize_state_for_variant(
    variant: str,
    raw_state: Any,
    step_idx: int,
    caption: str,
    max_line: int,
) -> dict[str, Any]:
    if variant == "oop_dispatch":
        return _sanitize_oop_dispatch_state(raw_state)
    if variant == "error_contrast":
        return _sanitize_error_contrast_state(raw_state, max_line)
    if variant == "data_structure":
        return _sanitize_data_structure_state(raw_state, caption)
    if variant == "sql_pipeline":
        return _sanitize_sql_pipeline_state(raw_state, caption)
    return _sanitize_execution_trace_state(raw_state, step_idx, caption)


def _default_checkpoint_for_variant(variant: str) -> dict[str, Any]:
    if variant == "oop_dispatch":
        return {
            "enabled": True,
            "question": "¿Qué versión del método ejecuta la JVM en tiempo de ejecución?",
            "options": [
                "La versión sobrescrita (@Override) del objeto real en el heap",
                "La versión de la clase padre según el tipo estático",
                "Falla en compilación por ambigüedad de tipos",
            ],
            "correct_index": 0,
            "explanation": "El despacho dinámico resuelve el método según el tipo dinámico del objeto en el heap.",
        }
    if variant == "error_contrast":
        return {
            "enabled": True,
            "question": "¿Qué ocurre en la pila de llamadas al lanzarse la excepción?",
            "options": [
                "Desenrolla marcos activos hasta hallar un catch compatible",
                "Ignora la línea con fallo y continúa en la siguiente instrucción",
                "Reinicia automáticamente el método desde la primera línea",
            ],
            "correct_index": 0,
            "explanation": "El stack unwinding desapila marcos hasta encontrar un manejador catch compatible.",
        }
    if variant == "data_structure":
        return {
            "enabled": True,
            "question": "¿Qué garantiza actualizar referencias e índices en orden correcto?",
            "options": [
                "Conservar acceso O(1)/enlaces íntegros sin perder elementos",
                "Reducir el tamaño físico en disco a cero bytes",
                "Ordenar alfabéticamente toda la estructura en cada lectura",
            ],
            "correct_index": 0,
            "explanation": "Mantener tamaño, capacidad y punteros sincronizados preserva el invariante de la colección.",
        }
    if variant == "sql_pipeline":
        return {
            "enabled": True,
            "question": "¿Qué cláusula filtra grupos después de aplicar GROUP BY?",
            "options": [
                "HAVING sobre funciones de agregación del grupo",
                "WHERE antes de construir las tablas origen",
                "ORDER BY eliminando filas nulas automáticamente",
            ],
            "correct_index": 0,
            "explanation": "WHERE filtra filas individuales antes de agrupar; HAVING filtra grupos ya agregados.",
        }
    return {
        "enabled": True,
        "question": "¿Qué almacena la variable de referencia en el marco de pila?",
        "options": [
            "La dirección del objeto en el heap (@0x1A), no una copia completa",
            "Una copia independiente de todos los atributos del objeto",
            "Únicamente el nombre textual de la clase compilada",
        ],
        "correct_index": 0,
        "explanation": "En el stack vive la referencia que apunta a la instancia real alojada en el heap.",
    }


def _disabled_checkpoint() -> dict[str, Any]:
    return {
        "enabled": False,
        "question": "",
        "options": [],
        "correct_index": 0,
        "explanation": "",
    }


def _build_fallback_code_storyboard(
    *,
    variant: str,
    language: str,
    node_title: str,
    node_summary: str,
    story_script: str,
) -> dict[str, Any]:
    """Construye un storyboard determinista completo y rico para cualquiera de las 5 variantes."""
    clean_title = (node_title or "Traza Interactiva").strip()[:80]
    norm_context = _strip_accents_lower(f"{node_title} {node_summary} {story_script}")

    if variant == "sql_pipeline":
        source_code = (
            "SELECT\n"
            "    d.nombre AS depto,\n"
            "    COUNT(e.id) AS total,\n"
            "    AVG(e.sueldo) AS promedio\n"
            "FROM empleados e\n"
            "INNER JOIN departamentos d ON e.depto_id = d.id\n"
            "WHERE e.activo = 1\n"
            "GROUP BY d.nombre\n"
            "HAVING COUNT(e.id) >= 2\n"
            "ORDER BY promedio DESC;"
        )
        subgoals = [
            {"id": "sg1", "label": "1. Origen y combinación (FROM / JOIN)"},
            {"id": "sg2", "label": "2. Filtrado y agrupación (WHERE / GROUP BY)"},
            {"id": "sg3", "label": "3. Filtro de grupos y proyección (HAVING / SELECT)"},
        ]
        raw_steps: list[dict[str, Any]] = [
            {
                "subgoal_id": "sg1",
                "active_lines": [5],
                "caption": "FROM carga las filas base de la tabla empleados.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "active_clause": "FROM",
                    "pipeline_stages": list(_SQL_PIPELINE_STAGES),
                    "clause_sql": "FROM empleados e",
                    "columns": ["e.id", "e.nombre", "e.depto_id", "e.activo", "e.sueldo"],
                    "rows": [
                        {"values": ["1", "Ana", "10", "1", "1200"], "status": "kept", "group_key": None},
                        {"values": ["2", "Luis", "10", "1", "1500"], "status": "kept", "group_key": None},
                        {"values": ["3", "Mar", "20", "0", "1100"], "status": "kept", "group_key": None},
                        {"values": ["4", "Sol", "20", "1", "1400"], "status": "kept", "group_key": None},
                    ],
                    "note": "El motor relacional comienza leyendo las tuplas fuente antes de proyectar SELECT.",
                },
            },
            {
                "subgoal_id": "sg1",
                "active_lines": [6],
                "caption": "INNER JOIN enlaza cada empleado con su departamento.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "active_clause": "JOIN",
                    "pipeline_stages": list(_SQL_PIPELINE_STAGES),
                    "clause_sql": "INNER JOIN departamentos d ON e.depto_id = d.id",
                    "columns": ["e.nombre", "d.nombre", "e.activo", "e.sueldo"],
                    "rows": [
                        {"values": ["Ana", "Datos", "1", "1200"], "status": "kept", "group_key": None},
                        {"values": ["Luis", "Datos", "1", "1500"], "status": "kept", "group_key": None},
                        {"values": ["Mar", "Redes", "0", "1100"], "status": "kept", "group_key": None},
                        {"values": ["Sol", "Redes", "1", "1400"], "status": "kept", "group_key": None},
                    ],
                    "note": "Cada clave foránea e.depto_id empareja su fila con d.id.",
                },
            },
            {
                "subgoal_id": "sg2",
                "active_lines": [7],
                "caption": "WHERE descarta empleados inactivos antes de agrupar.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "active_clause": "WHERE",
                    "pipeline_stages": list(_SQL_PIPELINE_STAGES),
                    "clause_sql": "WHERE e.activo = 1",
                    "columns": ["e.nombre", "d.nombre", "e.activo", "e.sueldo"],
                    "rows": [
                        {"values": ["Ana", "Datos", "1", "1200"], "status": "kept", "group_key": None},
                        {"values": ["Luis", "Datos", "1", "1500"], "status": "kept", "group_key": None},
                        {"values": ["Mar", "Redes", "0", "1100"], "status": "filtered_out", "group_key": None},
                        {"values": ["Sol", "Redes", "1", "1400"], "status": "kept", "group_key": None},
                    ],
                    "note": "Mar queda fuera porque e.activo = 0 no cumple el predicado WHERE.",
                },
            },
            {
                "subgoal_id": "sg2",
                "active_lines": [8],
                "caption": "GROUP BY colapsa filas activas por nombre de departamento.",
                "checkpoint": _default_checkpoint_for_variant("sql_pipeline"),
                "state": {
                    "active_clause": "GROUP BY",
                    "pipeline_stages": list(_SQL_PIPELINE_STAGES),
                    "clause_sql": "GROUP BY d.nombre",
                    "columns": ["d.nombre", "COUNT(e.id)", "AVG(e.sueldo)"],
                    "rows": [
                        {"values": ["Datos", "2", "1350"], "status": "grouped", "group_key": "Datos"},
                        {"values": ["Redes", "1", "1400"], "status": "grouped", "group_key": "Redes"},
                    ],
                    "note": "Datos reúne 2 filas activas; Redes queda con solo 1 fila activa.",
                },
            },
            {
                "subgoal_id": "sg3",
                "active_lines": [9],
                "caption": "HAVING filtra grupos exigiendo al menos dos integrantes.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "active_clause": "HAVING",
                    "pipeline_stages": list(_SQL_PIPELINE_STAGES),
                    "clause_sql": "HAVING COUNT(e.id) >= 2",
                    "columns": ["d.nombre", "COUNT(e.id)", "AVG(e.sueldo)"],
                    "rows": [
                        {"values": ["Datos", "2", "1350"], "status": "kept", "group_key": "Datos"},
                        {"values": ["Redes", "1", "1400"], "status": "filtered_out", "group_key": "Redes"},
                    ],
                    "note": "Redes se descarta en HAVING porque su conteo agregado es 1 (< 2).",
                },
            },
            {
                "subgoal_id": "sg3",
                "active_lines": [1, 2, 3, 4, 10],
                "caption": "SELECT proyecta alias finales y ORDER BY ordena resultado.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "active_clause": "SELECT",
                    "pipeline_stages": list(_SQL_PIPELINE_STAGES),
                    "clause_sql": "SELECT d.nombre AS depto, COUNT(e.id) AS total, AVG(e.sueldo) AS promedio",
                    "columns": ["depto", "total", "promedio"],
                    "rows": [
                        {"values": ["Datos", "2", "1350"], "status": "projected", "group_key": "Datos"},
                    ],
                    "note": "Recién al final se proyectan las columnas definitivas y se ordena la salida.",
                },
            },
        ]
        s_idx = _compute_sentence_indices([None] * len(raw_steps), story_script, len(raw_steps))
        for i, st in enumerate(raw_steps):
            st["index"] = i
            st["sentence_index"] = s_idx[i]
        return {
            "variant": "sql_pipeline",
            "language": "sql",
            "title": clean_title,
            "source_code": source_code,
            "fixed_code": None,
            "subgoals": subgoals,
            "steps": raw_steps,
        }

    if variant == "oop_dispatch":
        source_code = (
            "class Notificador {\n"
            "    public String enviar(String msg) { return \"[BASE] \" + msg; }\n"
            "}\n"
            "class NotificadorPush extends Notificador {\n"
            "    @Override\n"
            "    public String enviar(String msg) {\n"
            "        return super.enviar(msg) + \" -> PUSH\";\n"
            "    }\n"
            "}\n"
            "public class DemoDespacho {\n"
            "    public static void main(String[] args) {\n"
            "        Notificador canal = new NotificadorPush();\n"
            "        String res = canal.enviar(\"Alerta\");\n"
            "    }\n"
            "}"
        )
        subgoals = [
            {"id": "sg1", "label": "1. Jerarquía y sobrescritura (@Override)"},
            {"id": "sg2", "label": "2. Referencia polimórfica (tipo estático vs dinámico)"},
            {"id": "sg3", "label": "3. Despacho dinámico y delegación con super"},
        ]
        raw_steps = [
            {
                "subgoal_id": "sg1",
                "active_lines": [1, 4, 5],
                "caption": "NotificadorPush extiende Notificador y sobrescribe enviar con @Override.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "classes": [
                        {"name": "Notificador", "parent": None, "methods": ["enviar(String)"], "active": True},
                        {
                            "name": "NotificadorPush",
                            "parent": "Notificador",
                            "methods": ["@Override enviar(String)"],
                            "active": True,
                        },
                    ],
                    "references": [],
                    "heap_objects": [],
                    "dispatch": {
                        "call_expr": "definición de jerarquía",
                        "static_check": "Firma enviar(String) compatible en ambas clases",
                        "lookup_path": ["NotificadorPush", "Notificador"],
                        "resolved_class": "NotificadorPush",
                        "resolved_method": "enviar(String)",
                        "via_super": False,
                    },
                },
            },
            {
                "subgoal_id": "sg2",
                "active_lines": [12],
                "caption": "Se instancia NotificadorPush en el heap bajo referencia Notificador.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "classes": [
                        {"name": "Notificador", "parent": None, "methods": ["enviar(String)"], "active": False},
                        {
                            "name": "NotificadorPush",
                            "parent": "Notificador",
                            "methods": ["@Override enviar(String)"],
                            "active": True,
                        },
                    ],
                    "references": [
                        {
                            "var_name": "canal",
                            "static_type": "Notificador",
                            "dynamic_type": "NotificadorPush",
                            "heap_id": "obj1",
                        }
                    ],
                    "heap_objects": [
                        {"id": "obj1", "class_name": "NotificadorPush", "fields": [{"name": "modo", "value": "\"PUSH\""}]}
                    ],
                    "dispatch": {
                        "call_expr": "new NotificadorPush()",
                        "static_check": "Upcasting implícito NotificadorPush -> Notificador válido",
                        "lookup_path": ["NotificadorPush"],
                        "resolved_class": "NotificadorPush",
                        "resolved_method": "<init>()",
                        "via_super": False,
                    },
                },
            },
            {
                "subgoal_id": "sg2",
                "active_lines": [13],
                "caption": "El compilador valida canal.enviar usando el tipo estático Notificador.",
                "checkpoint": _default_checkpoint_for_variant("oop_dispatch"),
                "state": {
                    "classes": [
                        {"name": "Notificador", "parent": None, "methods": ["enviar(String)"], "active": True},
                        {
                            "name": "NotificadorPush",
                            "parent": "Notificador",
                            "methods": ["@Override enviar(String)"],
                            "active": False,
                        },
                    ],
                    "references": [
                        {
                            "var_name": "canal",
                            "static_type": "Notificador",
                            "dynamic_type": "NotificadorPush",
                            "heap_id": "obj1",
                        }
                    ],
                    "heap_objects": [
                        {"id": "obj1", "class_name": "NotificadorPush", "fields": [{"name": "modo", "value": "\"PUSH\""}]}
                    ],
                    "dispatch": {
                        "call_expr": "canal.enviar(\"Alerta\")",
                        "static_check": "Notificador declara enviar(String): compilación exitosa",
                        "lookup_path": ["Notificador"],
                        "resolved_class": "NotificadorPush",
                        "resolved_method": "enviar(String)",
                        "via_super": False,
                    },
                },
            },
            {
                "subgoal_id": "sg3",
                "active_lines": [6, 7],
                "caption": "En ejecución, la JVM despacha NotificadorPush.enviar desde obj1.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "classes": [
                        {"name": "Notificador", "parent": None, "methods": ["enviar(String)"], "active": False},
                        {
                            "name": "NotificadorPush",
                            "parent": "Notificador",
                            "methods": ["@Override enviar(String)"],
                            "active": True,
                        },
                    ],
                    "references": [
                        {
                            "var_name": "canal",
                            "static_type": "Notificador",
                            "dynamic_type": "NotificadorPush",
                            "heap_id": "obj1",
                        }
                    ],
                    "heap_objects": [
                        {"id": "obj1", "class_name": "NotificadorPush", "fields": [{"name": "modo", "value": "\"PUSH\""}]}
                    ],
                    "dispatch": {
                        "call_expr": "canal.enviar(\"Alerta\")",
                        "static_check": "Notificador.enviar(String)",
                        "lookup_path": ["NotificadorPush"],
                        "resolved_class": "NotificadorPush",
                        "resolved_method": "NotificadorPush.enviar(String)",
                        "via_super": False,
                    },
                },
            },
            {
                "subgoal_id": "sg3",
                "active_lines": [2, 7],
                "caption": "super.enviar delega explícitamente la lógica base hacia Notificador.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "classes": [
                        {"name": "Notificador", "parent": None, "methods": ["enviar(String)"], "active": True},
                        {
                            "name": "NotificadorPush",
                            "parent": "Notificador",
                            "methods": ["@Override enviar(String)"],
                            "active": True,
                        },
                    ],
                    "references": [
                        {
                            "var_name": "canal",
                            "static_type": "Notificador",
                            "dynamic_type": "NotificadorPush",
                            "heap_id": "obj1",
                        }
                    ],
                    "heap_objects": [
                        {"id": "obj1", "class_name": "NotificadorPush", "fields": [{"name": "modo", "value": "\"PUSH\""}]}
                    ],
                    "dispatch": {
                        "call_expr": "super.enviar(\"Alerta\")",
                        "static_check": "Acceso a superclase directa Notificador",
                        "lookup_path": ["NotificadorPush", "Notificador"],
                        "resolved_class": "Notificador",
                        "resolved_method": "Notificador.enviar(String)",
                        "via_super": True,
                    },
                },
            },
            {
                "subgoal_id": "sg3",
                "active_lines": [13],
                "caption": "Retorna el resultado combinado en res sin romper polimorfismo.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "classes": [
                        {"name": "Notificador", "parent": None, "methods": ["enviar(String)"], "active": False},
                        {
                            "name": "NotificadorPush",
                            "parent": "Notificador",
                            "methods": ["@Override enviar(String)"],
                            "active": True,
                        },
                    ],
                    "references": [
                        {
                            "var_name": "canal",
                            "static_type": "Notificador",
                            "dynamic_type": "NotificadorPush",
                            "heap_id": "obj1",
                        }
                    ],
                    "heap_objects": [
                        {
                            "id": "obj1",
                            "class_name": "NotificadorPush",
                            "fields": [{"name": "ultimoEnvio", "value": "\"[BASE] Alerta -> PUSH\""}],
                        }
                    ],
                    "dispatch": {
                        "call_expr": "res = \"[BASE] Alerta -> PUSH\"",
                        "static_check": "Retorno String asignado correctamente",
                        "lookup_path": ["NotificadorPush", "Notificador"],
                        "resolved_class": "NotificadorPush",
                        "resolved_method": "enviar(String)",
                        "via_super": True,
                    },
                },
            },
        ]
        s_idx = _compute_sentence_indices([None] * len(raw_steps), story_script, len(raw_steps))
        for i, st in enumerate(raw_steps):
            st["index"] = i
            st["sentence_index"] = s_idx[i]
        return {
            "variant": "oop_dispatch",
            "language": language if language in ("java", "python") else "java",
            "title": clean_title,
            "source_code": source_code,
            "fixed_code": None,
            "subgoals": subgoals,
            "steps": raw_steps,
        }

    if variant == "error_contrast":
        source_code = (
            "public class ValidadorCodigo {\n"
            "    static String normalizar(String codigo) {\n"
            "        return codigo.trim().toUpperCase();\n"
            "    }\n"
            "    public static void main(String[] args) {\n"
            "        try {\n"
            "            String limpio = normalizar(null);\n"
            "            System.out.println(limpio);\n"
            "        } catch (NullPointerException e) {\n"
            "            System.out.println(\"Error: codigo nulo\");\n"
            "        }\n"
            "    }\n"
            "}"
        )
        fixed_code = (
            "public class ValidadorCodigo {\n"
            "    static String normalizar(String codigo) {\n"
            "        if (codigo == null) {\n"
            "            return \"SIN_CODIGO\";\n"
            "        }\n"
            "        return codigo.trim().toUpperCase();\n"
            "    }\n"
            "    public static void main(String[] args) {\n"
            "        String limpio = normalizar(null);\n"
            "        System.out.println(limpio);\n"
            "    }\n"
            "}"
        )
        contrast_info = {
            "bug_cause": "Se invoca codigo.trim() directamente cuando la referencia codigo es null.",
            "broken_line": "return codigo.trim().toUpperCase();",
            "fixed_line": "if (codigo == null) { return \"SIN_CODIGO\"; }",
            "fix_explanation": "Validar null en la frontera del método evita lanzar NullPointerException innecesariamente.",
        }
        subgoals = [
            {"id": "sg1", "label": "1. Ejecución hasta el punto de fallo"},
            {"id": "sg2", "label": "2. Desenrollado de pila y captura (try / catch)"},
            {"id": "sg3", "label": "3. Contraste con el código defensivo corregido"},
        ]
        raw_steps = [
            {
                "subgoal_id": "sg1",
                "active_lines": [6, 7],
                "caption": "main entra al bloque try e invoca normalizar(null).",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "phase": "running",
                    "code_view": "broken",
                    "exception": None,
                    "call_stack": [
                        {"frame": "main(String[])", "status": "active", "line": 7},
                    ],
                    "contrast": contrast_info,
                },
            },
            {
                "subgoal_id": "sg1",
                "active_lines": [2, 3],
                "caption": "normalizar recibe codigo = null e intenta ejecutar trim().",
                "checkpoint": _default_checkpoint_for_variant("error_contrast"),
                "state": {
                    "phase": "running",
                    "code_view": "broken",
                    "exception": None,
                    "call_stack": [
                        {"frame": "main(String[])", "status": "active", "line": 7},
                        {"frame": "normalizar(codigo=null)", "status": "active", "line": 3},
                    ],
                    "contrast": contrast_info,
                },
            },
            {
                "subgoal_id": "sg2",
                "active_lines": [3],
                "caption": "Desreferenciar null aborta línea 3 lanzando NullPointerException.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "phase": "exception_thrown",
                    "code_view": "broken",
                    "exception": {
                        "type": "NullPointerException",
                        "message": "Cannot invoke String.trim() because codigo is null",
                        "line": 3,
                    },
                    "call_stack": [
                        {"frame": "main(String[])", "status": "active", "line": 7},
                        {"frame": "normalizar(codigo=null)", "status": "crashed", "line": 3},
                    ],
                    "contrast": contrast_info,
                },
            },
            {
                "subgoal_id": "sg2",
                "active_lines": [7, 8],
                "caption": "La excepción desenrolla normalizar y salta println de línea 8.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "phase": "stack_unwinding",
                    "code_view": "broken",
                    "exception": {
                        "type": "NullPointerException",
                        "message": "Cannot invoke String.trim() because codigo is null",
                        "line": 3,
                    },
                    "call_stack": [
                        {"frame": "main(String[])", "status": "catching", "line": 9},
                        {"frame": "normalizar(codigo=null)", "status": "unwinding", "line": 3},
                    ],
                    "contrast": contrast_info,
                },
            },
            {
                "subgoal_id": "sg2",
                "active_lines": [9, 10],
                "caption": "El bloque catch intercepta la excepción y maneja el error.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "phase": "caught",
                    "code_view": "broken",
                    "exception": {
                        "type": "NullPointerException",
                        "message": "Capturada en catch (NullPointerException e)",
                        "line": 9,
                    },
                    "call_stack": [
                        {"frame": "main(String[]) [catch]", "status": "catching", "line": 10},
                    ],
                    "contrast": contrast_info,
                },
            },
            {
                "subgoal_id": "sg3",
                "active_lines": [3, 4, 5],
                "caption": "Con guarda de null explícita el flujo termina sin excepción.",
                "checkpoint": _disabled_checkpoint(),
                "state": {
                    "phase": "contrast_fix",
                    "code_view": "fixed",
                    "exception": None,
                    "call_stack": [
                        {"frame": "main(String[])", "status": "ok", "line": 10},
                        {"frame": "normalizar(codigo=null)", "status": "ok", "line": 4},
                    ],
                    "contrast": contrast_info,
                },
            },
        ]
        s_idx = _compute_sentence_indices([None] * len(raw_steps), story_script, len(raw_steps))
        for i, st in enumerate(raw_steps):
            st["index"] = i
            st["sentence_index"] = s_idx[i]
        return {
            "variant": "error_contrast",
            "language": language if language in ("java", "python", "c") else "java",
            "title": clean_title,
            "source_code": source_code,
            "fixed_code": fixed_code,
            "subgoals": subgoals,
            "steps": raw_steps,
        }

    if variant == "data_structure":
        is_hashmap = bool(re.search(r"hashmap|bucket|diccionario|hashcode", norm_context))
        if is_hashmap:
            source_code = (
                "import java.util.HashMap;\n"
                "public class IndiceCursos {\n"
                "    public static void main(String[] args) {\n"
                "        HashMap<String, Integer> cupos = new HashMap<>(4);\n"
                "        cupos.put(\"INF1\", 40);\n"
                "        cupos.put(\"MAT2\", 35);\n"
                "        cupos.put(\"INF1\", 45);\n"
                "        int actual = cupos.get(\"INF1\");\n"
                "    }\n"
                "}"
            )
            subgoals = [
                {"id": "sg1", "label": "1. Inicialización de tabla de buckets"},
                {"id": "sg2", "label": "2. Inserción por función hash (put)"},
                {"id": "sg3", "label": "3. Reemplazo de clave existente y consulta O(1)"},
            ]
            raw_steps = [
                {
                    "subgoal_id": "sg1",
                    "active_lines": [4],
                    "caption": "Reserva arreglo interno de 4 buckets inicialmente vacíos.",
                    "checkpoint": _disabled_checkpoint(),
                    "state": {
                        "structure_type": "hashmap",
                        "label": "cupos (HashMap<String, Integer>)",
                        "size": 0,
                        "capacity": 4,
                        "cells": [],
                        "pointers": [],
                        "buckets": [
                            {"bucket": 0, "entries": []},
                            {"bucket": 1, "entries": []},
                            {"bucket": 2, "entries": []},
                            {"bucket": 3, "entries": []},
                        ],
                        "operation": "new HashMap<>(4)",
                    },
                },
                {
                    "subgoal_id": "sg2",
                    "active_lines": [5],
                    "caption": "Calcula hash de INF1 y guarda 40 en bucket 1.",
                    "checkpoint": _disabled_checkpoint(),
                    "state": {
                        "structure_type": "hashmap",
                        "label": "cupos (HashMap<String, Integer>)",
                        "size": 1,
                        "capacity": 4,
                        "cells": [],
                        "pointers": [{"name": "bucket", "index": 1}],
                        "buckets": [
                            {"bucket": 0, "entries": []},
                            {
                                "bucket": 1,
                                "entries": [
                                    {"key": "\"INF1\"", "value": "40", "hash_formula": "hash(\"INF1\") % 4 = 1", "active": True}
                                ],
                            },
                            {"bucket": 2, "entries": []},
                            {"bucket": 3, "entries": []},
                        ],
                        "operation": "put(\"INF1\", 40)",
                    },
                },
                {
                    "subgoal_id": "sg2",
                    "active_lines": [6],
                    "caption": "Calcula hash de MAT2 e inserta 35 en bucket 3.",
                    "checkpoint": _default_checkpoint_for_variant("data_structure"),
                    "state": {
                        "structure_type": "hashmap",
                        "label": "cupos (HashMap<String, Integer>)",
                        "size": 2,
                        "capacity": 4,
                        "cells": [],
                        "pointers": [{"name": "bucket", "index": 3}],
                        "buckets": [
                            {"bucket": 0, "entries": []},
                            {
                                "bucket": 1,
                                "entries": [
                                    {"key": "\"INF1\"", "value": "40", "hash_formula": "hash(\"INF1\") % 4 = 1", "active": False}
                                ],
                            },
                            {"bucket": 2, "entries": []},
                            {
                                "bucket": 3,
                                "entries": [
                                    {"key": "\"MAT2\"", "value": "35", "hash_formula": "hash(\"MAT2\") % 4 = 3", "active": True}
                                ],
                            },
                        ],
                        "operation": "put(\"MAT2\", 35)",
                    },
                },
                {
                    "subgoal_id": "sg3",
                    "active_lines": [7],
                    "caption": "Clave INF1 coincide con equals(): sobrescribe valor 40 por 45.",
                    "checkpoint": _disabled_checkpoint(),
                    "state": {
                        "structure_type": "hashmap",
                        "label": "cupos (HashMap<String, Integer>)",
                        "size": 2,
                        "capacity": 4,
                        "cells": [],
                        "pointers": [{"name": "bucket", "index": 1}],
                        "buckets": [
                            {"bucket": 0, "entries": []},
                            {
                                "bucket": 1,
                                "entries": [
                                    {"key": "\"INF1\"", "value": "45", "hash_formula": "equals(\"INF1\") -> update", "active": True}
                                ],
                            },
                            {"bucket": 2, "entries": []},
                            {
                                "bucket": 3,
                                "entries": [
                                    {"key": "\"MAT2\"", "value": "35", "hash_formula": "hash(\"MAT2\") % 4 = 3", "active": False}
                                ],
                            },
                        ],
                        "operation": "put(\"INF1\", 45) -> actualiza sin duplicar clave",
                    },
                },
                {
                    "subgoal_id": "sg3",
                    "active_lines": [8],
                    "caption": "get(\"INF1\") salta directo al bucket 1 en tiempo O(1).",
                    "checkpoint": _disabled_checkpoint(),
                    "state": {
                        "structure_type": "hashmap",
                        "label": "cupos (HashMap<String, Integer>)",
                        "size": 2,
                        "capacity": 4,
                        "cells": [],
                        "pointers": [{"name": "lookup", "index": 1}],
                        "buckets": [
                            {"bucket": 0, "entries": []},
                            {
                                "bucket": 1,
                                "entries": [
                                    {"key": "\"INF1\"", "value": "45", "hash_formula": "bucket 1 -> retorna 45", "active": True}
                                ],
                            },
                            {"bucket": 2, "entries": []},
                            {
                                "bucket": 3,
                                "entries": [
                                    {"key": "\"MAT2\"", "value": "35", "hash_formula": "hash(\"MAT2\") % 4 = 3", "active": False}
                                ],
                            },
                        ],
                        "operation": "get(\"INF1\") -> 45",
                    },
                },
                {
                    "subgoal_id": "sg3",
                    "active_lines": [8, 9],
                    "caption": "La consulta finaliza conservando tamaño 2 y claves únicas.",
                    "checkpoint": _disabled_checkpoint(),
                    "state": {
                        "structure_type": "hashmap",
                        "label": "cupos (HashMap<String, Integer>)",
                        "size": 2,
                        "capacity": 4,
                        "cells": [],
                        "pointers": [],
                        "buckets": [
                            {"bucket": 0, "entries": []},
                            {
                                "bucket": 1,
                                "entries": [
                                    {"key": "\"INF1\"", "value": "45", "hash_formula": "hash % 4 = 1", "active": False}
                                ],
                            },
                            {"bucket": 2, "entries": []},
                            {
                                "bucket": 3,
                                "entries": [
                                    {"key": "\"MAT2\"", "value": "35", "hash_formula": "hash % 4 = 3", "active": False}
                                ],
                            },
                        ],
                        "operation": "actual = 45 (invariante intacto)",
                    },
                },
            ]
        else:
            source_code = (
                "import java.util.ArrayList;\n"
                "public class ColaTareas {\n"
                "    public static void main(String[] args) {\n"
                "        ArrayList<String> tareas = new ArrayList<>(4);\n"
                "        tareas.add(\"Diseño\");\n"
                "        tareas.add(\"Código\");\n"
                "        tareas.add(\"Tests\");\n"
                "        tareas.set(1, \"Refactor\");\n"
                "        tareas.remove(0);\n"
                "    }\n"
                "}"
            )
            subgoals = [
                {"id": "sg1", "label": "1. Reserva contigua e inserción al final (add)"},
                {"id": "sg2", "label": "2. Acceso y mutación directa por índice (set)"},
                {"id": "sg3", "label": "3. Eliminación y desplazamiento a la izquierda (remove)"},
            ]
            raw_steps = [
                {
                    "subgoal_id": "sg1",
                    "active_lines": [4],
                    "caption": "Crea ArrayList con capacidad inicial para cuatro referencias contiguas.",
                    "checkpoint": _disabled_checkpoint(),
                    "state": {
                        "structure_type": "arraylist",
                        "label": "tareas (ArrayList<String>)",
                        "size": 0,
                        "capacity": 4,
                        "cells": [
                            {"index": 0, "value": "", "state": "empty", "next_index": None},
                            {"index": 1, "value": "", "state": "empty", "next_index": None},
                            {"index": 2, "value": "", "state": "empty", "next_index": None},
                            {"index": 3, "value": "", "state": "empty", "next_index": None},
                        ],
                        "pointers": [{"name": "size", "index": 0}],
                        "buckets": [],
                        "operation": "new ArrayList<>(4)",
                    },
                },
                {
                    "subgoal_id": "sg1",
                    "active_lines": [5, 6],
                    "caption": "Inserta Diseño en índice 0 y Código en índice 1.",
                    "checkpoint": _disabled_checkpoint(),
                    "state": {
                        "structure_type": "arraylist",
                        "label": "tareas (ArrayList<String>)",
                        "size": 2,
                        "capacity": 4,
                        "cells": [
                            {"index": 0, "value": "\"Diseño\"", "state": "normal", "next_index": None},
                            {"index": 1, "value": "\"Código\"", "state": "changed", "next_index": None},
                            {"index": 2, "value": "", "state": "empty", "next_index": None},
                            {"index": 3, "value": "", "state": "empty", "next_index": None},
                        ],
                        "pointers": [{"name": "size", "index": 2}],
                        "buckets": [],
                        "operation": "add(\"Diseño\"), add(\"Código\")",
                    },
                },
                {
                    "subgoal_id": "sg1",
                    "active_lines": [7],
                    "caption": "Agrega Tests al final ocupando el índice 2 en O(1).",
                    "checkpoint": _default_checkpoint_for_variant("data_structure"),
                    "state": {
                        "structure_type": "arraylist",
                        "label": "tareas (ArrayList<String>)",
                        "size": 3,
                        "capacity": 4,
                        "cells": [
                            {"index": 0, "value": "\"Diseño\"", "state": "normal", "next_index": None},
                            {"index": 1, "value": "\"Código\"", "state": "normal", "next_index": None},
                            {"index": 2, "value": "\"Tests\"", "state": "changed", "next_index": None},
                            {"index": 3, "value": "", "state": "empty", "next_index": None},
                        ],
                        "pointers": [{"name": "size", "index": 3}],
                        "buckets": [],
                        "operation": "add(\"Tests\")",
                    },
                },
                {
                    "subgoal_id": "sg2",
                    "active_lines": [8],
                    "caption": "set(1, \"Refactor\") reemplaza directo la celda 1 en O(1).",
                    "checkpoint": _disabled_checkpoint(),
                    "state": {
                        "structure_type": "arraylist",
                        "label": "tareas (ArrayList<String>)",
                        "size": 3,
                        "capacity": 4,
                        "cells": [
                            {"index": 0, "value": "\"Diseño\"", "state": "normal", "next_index": None},
                            {"index": 1, "value": "\"Refactor\"", "state": "changed", "next_index": None},
                            {"index": 2, "value": "\"Tests\"", "state": "normal", "next_index": None},
                            {"index": 3, "value": "", "state": "empty", "next_index": None},
                        ],
                        "pointers": [{"name": "idx", "index": 1}],
                        "buckets": [],
                        "operation": "set(1, \"Refactor\")",
                    },
                },
                {
                    "subgoal_id": "sg3",
                    "active_lines": [9],
                    "caption": "remove(0) elimina Diseño y desplaza elementos restantes hacia izquierda.",
                    "checkpoint": _disabled_checkpoint(),
                    "state": {
                        "structure_type": "arraylist",
                        "label": "tareas (ArrayList<String>)",
                        "size": 2,
                        "capacity": 4,
                        "cells": [
                            {"index": 0, "value": "\"Refactor\"", "state": "changed", "next_index": None},
                            {"index": 1, "value": "\"Tests\"", "state": "changed", "next_index": None},
                            {"index": 2, "value": "", "state": "empty", "next_index": None},
                            {"index": 3, "value": "", "state": "empty", "next_index": None},
                        ],
                        "pointers": [{"name": "shift", "index": 0}, {"name": "size", "index": 2}],
                        "buckets": [],
                        "operation": "remove(0) -> desplazamiento O(n)",
                    },
                },
                {
                    "subgoal_id": "sg3",
                    "active_lines": [10],
                    "caption": "La lista queda compacta con tamaño 2 y capacidad 4.",
                    "checkpoint": _disabled_checkpoint(),
                    "state": {
                        "structure_type": "arraylist",
                        "label": "tareas (ArrayList<String>)",
                        "size": 2,
                        "capacity": 4,
                        "cells": [
                            {"index": 0, "value": "\"Refactor\"", "state": "active", "next_index": None},
                            {"index": 1, "value": "\"Tests\"", "state": "active", "next_index": None},
                            {"index": 2, "value": "", "state": "empty", "next_index": None},
                            {"index": 3, "value": "", "state": "empty", "next_index": None},
                        ],
                        "pointers": [{"name": "size", "index": 2}],
                        "buckets": [],
                        "operation": "Estado final consistente",
                    },
                },
            ]
        s_idx = _compute_sentence_indices([None] * len(raw_steps), story_script, len(raw_steps))
        for i, st in enumerate(raw_steps):
            st["index"] = i
            st["sentence_index"] = s_idx[i]
        return {
            "variant": "data_structure",
            "language": language if language in ("java", "python", "c") else "java",
            "title": clean_title,
            "source_code": source_code,
            "fixed_code": None,
            "subgoals": subgoals,
            "steps": raw_steps,
        }

    # 5. execution_trace (por defecto)
    source_code = (
        "public class CuentaEstudio {\n"
        "    private int saldo;\n"
        "    public CuentaEstudio(int inicial) {\n"
        "        this.saldo = inicial;\n"
        "    }\n"
        "    public void abonar(int monto) {\n"
        "        if (monto > 0) {\n"
        "            this.saldo += monto;\n"
        "        }\n"
        "    }\n"
        "    public static void main(String[] args) {\n"
        "        CuentaEstudio c = new CuentaEstudio(1000);\n"
        "        c.abonar(500);\n"
        "        System.out.println(c.saldo);\n"
        "    }\n"
        "}"
    )
    subgoals = [
        {"id": "sg1", "label": "1. Creación de instancia en el heap (new)"},
        {"id": "sg2", "label": "2. Llamada a método y marco en el stack"},
        {"id": "sg3", "label": "3. Mutación de estado y salida por consola"},
    ]
    raw_steps = [
        {
            "subgoal_id": "sg1",
            "active_lines": [11, 12],
            "caption": "main inicia y solicita crear un objeto CuentaEstudio(1000).",
            "checkpoint": _disabled_checkpoint(),
            "state": {
                "frames": [{"name": "main", "active": True, "vars": []}],
                "heap": [],
                "stdout": [],
                "delta": "Arranca el marco main en el stack",
            },
        },
        {
            "subgoal_id": "sg1",
            "active_lines": [3, 4],
            "caption": "El constructor reserva @0x1A en el heap e inicializa saldo.",
            "checkpoint": _disabled_checkpoint(),
            "state": {
                "frames": [
                    {"name": "main", "active": False, "vars": []},
                    {
                        "name": "CuentaEstudio(1000)",
                        "active": True,
                        "vars": [
                            {"name": "this", "value": "@0x1A", "type": "CuentaEstudio", "changed": True, "ref_id": "obj1"},
                            {"name": "inicial", "value": "1000", "type": "int", "changed": True, "ref_id": None},
                        ],
                    },
                ],
                "heap": [
                    {
                        "id": "obj1",
                        "class_name": "CuentaEstudio",
                        "address": "@0x1A",
                        "fields": [{"name": "saldo", "value": "1000", "changed": True}],
                    }
                ],
                "stdout": [],
                "delta": "Instancia obj1 creada con saldo = 1000",
            },
        },
        {
            "subgoal_id": "sg1",
            "active_lines": [12],
            "caption": "La variable local c guarda la referencia @0x1A en main.",
            "checkpoint": _default_checkpoint_for_variant("execution_trace"),
            "state": {
                "frames": [
                    {
                        "name": "main",
                        "active": True,
                        "vars": [
                            {"name": "c", "value": "@0x1A", "type": "CuentaEstudio", "changed": True, "ref_id": "obj1"}
                        ],
                    }
                ],
                "heap": [
                    {
                        "id": "obj1",
                        "class_name": "CuentaEstudio",
                        "address": "@0x1A",
                        "fields": [{"name": "saldo", "value": "1000", "changed": False}],
                    }
                ],
                "stdout": [],
                "delta": "c apunta a obj1 (@0x1A)",
            },
        },
        {
            "subgoal_id": "sg2",
            "active_lines": [6, 7, 13],
            "caption": "c.abonar(500) apila un nuevo marco con this = @0x1A.",
            "checkpoint": _disabled_checkpoint(),
            "state": {
                "frames": [
                    {
                        "name": "main",
                        "active": False,
                        "vars": [
                            {"name": "c", "value": "@0x1A", "type": "CuentaEstudio", "changed": False, "ref_id": "obj1"}
                        ],
                    },
                    {
                        "name": "abonar(500)",
                        "active": True,
                        "vars": [
                            {"name": "this", "value": "@0x1A", "type": "CuentaEstudio", "changed": True, "ref_id": "obj1"},
                            {"name": "monto", "value": "500", "type": "int", "changed": True, "ref_id": None},
                        ],
                    },
                ],
                "heap": [
                    {
                        "id": "obj1",
                        "class_name": "CuentaEstudio",
                        "address": "@0x1A",
                        "fields": [{"name": "saldo", "value": "1000", "changed": False}],
                    }
                ],
                "stdout": [],
                "delta": "Entra a abonar(500); valida monto > 0",
            },
        },
        {
            "subgoal_id": "sg3",
            "active_lines": [8],
            "caption": "this.saldo suma 500 mutando directamente el objeto @0x1A.",
            "checkpoint": _disabled_checkpoint(),
            "state": {
                "frames": [
                    {
                        "name": "main",
                        "active": False,
                        "vars": [
                            {"name": "c", "value": "@0x1A", "type": "CuentaEstudio", "changed": False, "ref_id": "obj1"}
                        ],
                    },
                    {
                        "name": "abonar(500)",
                        "active": True,
                        "vars": [
                            {"name": "this", "value": "@0x1A", "type": "CuentaEstudio", "changed": False, "ref_id": "obj1"},
                            {"name": "monto", "value": "500", "type": "int", "changed": False, "ref_id": None},
                        ],
                    },
                ],
                "heap": [
                    {
                        "id": "obj1",
                        "class_name": "CuentaEstudio",
                        "address": "@0x1A",
                        "fields": [{"name": "saldo", "value": "1500", "changed": True}],
                    }
                ],
                "stdout": [],
                "delta": "obj1.saldo cambia de 1000 a 1500",
            },
        },
        {
            "subgoal_id": "sg3",
            "active_lines": [14],
            "caption": "Se desapila abonar e imprime 1500 desde main.",
            "checkpoint": _disabled_checkpoint(),
            "state": {
                "frames": [
                    {
                        "name": "main",
                        "active": True,
                        "vars": [
                            {"name": "c", "value": "@0x1A", "type": "CuentaEstudio", "changed": False, "ref_id": "obj1"}
                        ],
                    }
                ],
                "heap": [
                    {
                        "id": "obj1",
                        "class_name": "CuentaEstudio",
                        "address": "@0x1A",
                        "fields": [{"name": "saldo", "value": "1500", "changed": False}],
                    }
                ],
                "stdout": ["1500"],
                "delta": "Consola emite 1500 tras desapilar abonar()",
            },
        },
    ]
    s_idx = _compute_sentence_indices([None] * len(raw_steps), story_script, len(raw_steps))
    for i, st in enumerate(raw_steps):
        st["index"] = i
        st["sentence_index"] = s_idx[i]
    return {
        "variant": "execution_trace",
        "language": language if language in _STORYBOARD_LANGUAGES else "java",
        "title": clean_title,
        "source_code": source_code,
        "fixed_code": None,
        "subgoals": subgoals,
        "steps": raw_steps,
    }


def _sanitize_storyboard_payload(
    parsed: dict[str, Any],
    *,
    heuristic_lang: str,
    heuristic_variant: str,
    node_title: str,
    node_summary: str,
    story_script: str,
) -> dict[str, Any]:
    raw_variant = str(parsed.get("variant") or heuristic_variant).strip().lower()
    if heuristic_lang == "sql" or heuristic_variant == "sql_pipeline":
        variant = "sql_pipeline"
    elif raw_variant in _STORYBOARD_VARIANTS:
        variant = raw_variant
    else:
        variant = heuristic_variant

    raw_lang = str(parsed.get("language") or heuristic_lang).strip().lower()
    if variant == "sql_pipeline":
        language = "sql"
    elif raw_lang in _STORYBOARD_LANGUAGES:
        language = raw_lang
    else:
        language = heuristic_lang if heuristic_lang in _STORYBOARD_LANGUAGES else "java"

    fallback_bundle = _build_fallback_code_storyboard(
        variant=variant,
        language=language,
        node_title=node_title,
        node_summary=node_summary,
        story_script=story_script,
    )

    title = str(parsed.get("title") or node_title or fallback_bundle["title"]).strip()[:100]
    if not title:
        title = fallback_bundle["title"]

    source_code = _clean_storyboard_code(parsed.get("source_code"), language, max_lines=22)
    if len(source_code.splitlines()) < 4:
        story_code = _extract_story_code_block(story_script, language)
        if story_code:
            source_code = story_code
        else:
            raise ValueError("source_code demasiado corto o ausente")

    fixed_code: str | None = None
    if variant == "error_contrast":
        cleaned_fixed = _clean_storyboard_code(parsed.get("fixed_code"), language, max_lines=22)
        if len(cleaned_fixed.splitlines()) >= 4:
            fixed_code = cleaned_fixed
        else:
            fixed_code = fallback_bundle["fixed_code"]
    elif parsed.get("fixed_code"):
        cleaned_opt = _clean_storyboard_code(parsed.get("fixed_code"), language, max_lines=22)
        fixed_code = cleaned_opt or None

    raw_subgoals = parsed.get("subgoals")
    subgoals: list[dict[str, str]] = []
    if isinstance(raw_subgoals, list):
        seen_ids: set[str] = set()
        for idx, sg in enumerate(raw_subgoals[:4]):
            if not isinstance(sg, dict):
                continue
            sg_id = str(sg.get("id") or f"sg{idx + 1}").strip()
            sg_label = str(sg.get("label") or f"Etapa {idx + 1}").strip()
            if sg_id and sg_label and sg_id not in seen_ids:
                seen_ids.add(sg_id)
                subgoals.append({"id": sg_id, "label": sg_label[:90]})
    if len(subgoals) < 2:
        subgoals = list(fallback_bundle["subgoals"])

    valid_sg_ids = {sg["id"] for sg in subgoals}

    raw_steps = parsed.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) < 4:
        raise ValueError("Se requieren al menos 4 pasos válidos en el storyboard")

    trimmed_steps = [st for st in raw_steps if isinstance(st, dict)][:9]
    if len(trimmed_steps) < 4:
        raise ValueError("Se requieren al menos 4 pasos tipo objeto en el storyboard")

    src_max_line = max(1, len(source_code.splitlines()))
    fix_max_line = max(1, len((fixed_code or source_code).splitlines()))

    raw_sent_indices: list[int | None] = []
    for st in trimmed_steps:
        si = st.get("sentence_index")
        if isinstance(si, int):
            raw_sent_indices.append(si)
        else:
            try:
                raw_sent_indices.append(int(si) if si is not None else None)
            except (TypeError, ValueError):
                raw_sent_indices.append(None)

    computed_sent_indices = _compute_sentence_indices(raw_sent_indices, story_script, len(trimmed_steps))

    clean_steps: list[dict[str, Any]] = []
    enabled_checkpoints = 0

    for idx, st in enumerate(trimmed_steps):
        raw_sg = str(st.get("subgoal_id") or "").strip()
        if raw_sg not in valid_sg_ids:
            raw_sg = subgoals[min(len(subgoals) - 1, (idx * len(subgoals)) // max(1, len(trimmed_steps)))]["id"]

        caption = _clean_micro_caption(st.get("caption"), f"Paso {idx + 1} de la traza.")
        sanitized_state = _sanitize_state_for_variant(variant, st.get("state"), idx, caption, src_max_line)

        step_max_line = (
            fix_max_line
            if variant == "error_contrast" and sanitized_state.get("code_view") == "fixed"
            else src_max_line
        )
        raw_lines = st.get("active_lines")
        active_lines: list[int] = []
        if isinstance(raw_lines, list):
            for ln in raw_lines[:8]:
                try:
                    ln_int = int(ln)
                except (TypeError, ValueError):
                    continue
                if 1 <= ln_int <= step_max_line and ln_int not in active_lines:
                    active_lines.append(ln_int)
        if not active_lines:
            active_lines = [min(step_max_line, idx + 1)]

        checkpoint_out = _disabled_checkpoint()
        raw_cp = st.get("checkpoint")
        if isinstance(raw_cp, dict) and bool(raw_cp.get("enabled")) and enabled_checkpoints < 2:
            cp_q = str(raw_cp.get("question") or "").strip()
            raw_opts = raw_cp.get("options")
            cp_opts = (
                [str(o).strip() for o in raw_opts[:4] if str(o).strip()]
                if isinstance(raw_opts, list)
                else []
            )
            if cp_q and len(cp_opts) >= 2:
                try:
                    c_idx = int(raw_cp.get("correct_index") or 0)
                except (TypeError, ValueError):
                    c_idx = 0
                c_idx = max(0, min(len(cp_opts) - 1, c_idx))
                cp_exp = str(raw_cp.get("explanation") or "Revisa el estado actual de la traza.").strip()
                checkpoint_out = {
                    "enabled": True,
                    "question": cp_q,
                    "options": cp_opts,
                    "correct_index": c_idx,
                    "explanation": cp_exp,
                }
                enabled_checkpoints += 1

        clean_steps.append(
            {
                "index": idx,
                "subgoal_id": raw_sg,
                "active_lines": active_lines,
                "caption": caption,
                "sentence_index": computed_sent_indices[idx],
                "checkpoint": checkpoint_out,
                "state": sanitized_state,
            }
        )

    if enabled_checkpoints == 0 and clean_steps:
        mid_idx = min(len(clean_steps) - 1, max(1, len(clean_steps) // 2))
        clean_steps[mid_idx]["checkpoint"] = _default_checkpoint_for_variant(variant)

    return {
        "variant": variant,
        "language": language,
        "title": title,
        "source_code": source_code,
        "fixed_code": fixed_code,
        "subgoals": subgoals,
        "steps": clean_steps,
    }


def generate_code_storyboard_with_ai(
    *,
    course_title: str,
    node_title: str,
    node_summary: str,
    story_script: str,
    engine_type: str = "code_lab",
    preferred_provider: str = "auto",
) -> tuple[dict[str, Any], str]:
    """Genera un storyboard interactivo auto-adaptativo (5 variantes) con IA o fallback determinista."""
    heuristic_lang, heuristic_variant = _detect_storyboard_language_and_variant(
        course_title=course_title,
        node_title=node_title,
        node_summary=node_summary,
        story_script=story_script,
    )
    sentences = split_story_sentences(story_script or "")
    story_code_hint = _extract_story_code_block(story_script, heuristic_lang)

    system_prompt = (
        "Eres el motor de visualizaciones algorítmicas y trazas de memoria de Brotal (v1.2.2).\n"
        "Debes generar un storyboard interactivo paso a paso en JSON válido para acompañar la explicación del nodo.\n"
        "REGLAS ESTRICTAS:\n"
        "1. Elige `variant` entre: 'execution_trace' | 'oop_dispatch' | 'error_contrast' | 'data_structure' | 'sql_pipeline'. "
        f"Variante sugerida por heurística: '{heuristic_variant}' (si el lenguaje es SQL DEBE ser 'sql_pipeline').\n"
        "2. `language`: 'java' | 'c' | 'python' | 'sql'.\n"
        "3. `source_code`: código limpio, indentado y pedagógico de 6 a 22 líneas.\n"
        "4. `fixed_code`: obligatorio (no vacío, 6 a 22 líneas) cuando `variant == 'error_contrast'`; `null` en las demás.\n"
        "5. `subgoals`: de 2 a 4 sub-objetivos `{id, label}`.\n"
        "6. `steps`: de 5 a 9 pasos ordenados (`index: 0..N-1`), cada uno con:\n"
        "   - `subgoal_id` existente en `subgoals`,\n"
        "   - `active_lines`: lista de líneas 1-based activas en ese paso,\n"
        "   - `caption`: micro-explicación en español de MÁXIMO 12 PALABRAS,\n"
        "   - `sentence_index`: entero `0..num_sentences-1` monótono creciente alineado a las oraciones de `story_script`,\n"
        "   - `checkpoint`: incluye entre 1 y 2 pasos (hacia la mitad/clímax) con `enabled: true`, `question` de predicción, "
        "`options` (2 a 4), `correct_index` y `explanation` breve; en los demás pasos usa `enabled: false`.\n"
        "   - `state`: objeto que DEBE respetar exactamente las claves de la variante elegida:\n"
        "     * execution_trace: {frames:[{name,active,vars:[{name,value,type,changed,ref_id}]}], "
        "heap:[{id,class_name,address,fields:[{name,value,changed}]}], stdout:[str], delta:str}\n"
        "     * oop_dispatch: {classes:[{name,parent,methods:[str],active}], "
        "references:[{var_name,static_type,dynamic_type,heap_id}], "
        "heap_objects:[{id,class_name,fields:[{name,value}]}], "
        "dispatch:{call_expr,static_check,lookup_path:[str],resolved_class,resolved_method,via_super}}\n"
        "     * error_contrast: {phase:'running'|'exception_thrown'|'stack_unwinding'|'caught'|'contrast_fix', "
        "code_view:'broken'|'fixed', exception:{type,message,line}|null, "
        "call_stack:[{frame,status:'active'|'crashed'|'unwinding'|'catching'|'ok',line}], "
        "contrast:{bug_cause,broken_line,fixed_line,fix_explanation}}\n"
        "     * data_structure: {structure_type:'array'|'arraylist'|'hashmap'|'linkedlist', label, size, capacity, "
        "cells:[{index,value,state:'normal'|'active'|'changed'|'empty',next_index}], pointers:[{name,index}], "
        "buckets:[{bucket,entries:[{key,value,hash_formula,active}]}], operation}\n"
        "     * sql_pipeline: {active_clause:'FROM'|'JOIN'|'WHERE'|'GROUP BY'|'HAVING'|'SELECT'|'ORDER BY', "
        "pipeline_stages:['FROM/JOIN','WHERE','GROUP BY','HAVING','SELECT','ORDER BY'], clause_sql, "
        "columns:[str], rows:[{values:[str],status:'kept'|'filtered_out'|'grouped'|'projected',group_key}], note}\n"
        "Responde ÚNICAMENTE un objeto JSON válido."
    )

    user_payload = {
        "course_title": course_title,
        "engine_type": engine_type,
        "node_title": node_title,
        "node_summary": node_summary,
        "suggested_language": heuristic_lang,
        "suggested_variant": heuristic_variant,
        "num_sentences": len(sentences),
        "story_sentences": sentences[:16],
        "extracted_code_block": story_code_hint,
    }

    try:
        comp = complete_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            preferred_provider=preferred_provider,
            json_mode=True,
            temperature=0.3,
            max_tokens=3600,
        )
        parsed = extract_json_object(comp.text)
        sanitized = _sanitize_storyboard_payload(
            parsed,
            heuristic_lang=heuristic_lang,
            heuristic_variant=heuristic_variant,
            node_title=node_title,
            node_summary=node_summary,
            story_script=story_script,
        )
        return (sanitized, comp.provider)
    except (AiProviderError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        fallback = _build_fallback_code_storyboard(
            variant=heuristic_variant,
            language=heuristic_lang,
            node_title=node_title,
            node_summary=node_summary,
            story_script=story_script,
        )
        return (fallback, "local_fallback")


# ---------------- Language Studio Interactive Practice Chat (v1.2.3) ----------------

_L1_ES_RECAST_RULES: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (
        re.compile(r"\b(she|he|it)\s+don't\b", re.IGNORECASE),
        r"\1 doesn't",
        "En 3.ª persona singular (he/she/it) usamos **doesn't** en lugar de don't.",
        "She doesn't study at night.",
    ),
    (
        re.compile(r"\b(she|he|it)\s+doesn't\s+(goes|studies|has|works|likes|plays|does)\b", re.IGNORECASE),
        r"\1 doesn't",
        "Después de **doesn't**, el verbo principal vuelve a su forma base sin -s.",
        "He doesn't have class on Saturday.",
    ),
    (
        re.compile(r"\b(she|he)\s+go\b", re.IGNORECASE),
        r"\1 goes",
        "En afirmativa de Present Simple con he/she agregamos **-es** (goes).",
        "She goes to university every morning.",
    ),
    (
        re.compile(r"\b(she|he)\s+study\b", re.IGNORECASE),
        r"\1 studies",
        "Con he/she en Present Simple, study cambia a **studies**.",
        "She studies English in the library.",
    ),
    (
        re.compile(r"\b(she|he)\s+have\b", re.IGNORECASE),
        r"\1 has",
        "Con he/she en afirmativa usamos **has** en lugar de have.",
        "He has two classes in the morning.",
    ),
    (
        re.compile(r"\bthere\s+is\s+(many|two|three|four|five|several|some\s+\w+s)\b", re.IGNORECASE),
        r"there are \1",
        "Para sustantivos en plural usamos **there are**, no there is.",
        "There are many students in the classroom.",
    ),
    (
        re.compile(r"\bi\s+have\s+(\d+)\s+years?\b", re.IGNORECASE),
        r"I am \1 years old",
        "En inglés la edad se expresa con **verb to be** (I am ... years old), no con have.",
        "I am twenty years old.",
    ),
    (
        re.compile(r"\bi\s+am\s+agree\b", re.IGNORECASE),
        "I agree",
        "**Agree** es un verbo principal: decimos **I agree**, sin am.",
        "I agree with that idea.",
    ),
    (
        re.compile(r"^\s*is\s+(important|good|easy|hard|interesting|raining|sunny)\b", re.IGNORECASE),
        r"It is \1",
        "En inglés nunca omitimos el sujeto: usa **It is** al inicio de la oración.",
        "It is important to practice every day.",
    ),
)


def _cap_en_words(text: str, max_words: int = 25) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    words = cleaned.split()
    if len(words) <= max_words:
        return cleaned
    trimmed = " ".join(words[:max_words]).rstrip(",;:")
    if trimmed and trimmed[-1] not in ".!?":
        trimmed += "."
    return trimmed


def _default_language_missions(node_title: str, node_summary: str) -> list[str]:
    ctx = f"{node_title} {node_summary}".lower()
    if any(k in ctx for k in ("there is", "there are", "quantifier", "countable", "uncountable", "classroom", "room")):
        return [
            "Describe two things in your room or classroom using 'There is' and 'There are'.",
            "Use 'some' or 'any' in a sentence about study objects or food.",
            "Ask one question with 'Is there...?' or 'Are there...?'.",
        ]
    if any(k in ctx for k in ("routine", "present simple", "habit", "daily", "frequency", "verb to be")):
        return [
            "Describe two activities from your daily routine using Present Simple.",
            "Mention something you or a classmate doesn't do on weekends.",
            "Ask one question using 'Do' or 'Does' about study habits.",
        ]
    return [
        f"Write one clear affirmative sentence in English about {node_title}.",
        f"Share a negative or contrasting idea using {node_title}.",
        f"Ask a simple question in English connected to {node_title}.",
    ]


def _default_lexical_chips(node_title: str, node_summary: str) -> list[str]:
    ctx = f"{node_title} {node_summary}".lower()
    if any(k in ctx for k in ("there is", "there are", "quantifier", "countable", "uncountable")):
        return ["There is", "There are", "some coffee", "any notebooks", "many students", "on the desk"]
    if any(k in ctx for k in ("routine", "present simple", "habit", "daily", "frequency")):
        return ["usually", "every morning", "studies", "doesn't have", "at university", "Do you...?"]
    return ["usually", "every day", "there are", "doesn't", "in class", "Do you...?"]


def _detect_l1_es_recast(message: str) -> tuple[str | None, str | None, str | None]:
    """Detecta errores frecuentes L1-español y devuelve (frase_corregida, explicacion_es, ejemplo_en)."""
    msg = (message or "").strip()
    if not msg:
        return (None, None, None)

    # Caso especial: doesn't + verbo con -s
    m_doesnt = re.search(
        r"\b(she|he|it)\s+doesn't\s+(goes|studies|has|works|likes|plays|does)\b",
        msg,
        flags=re.IGNORECASE,
    )
    if m_doesnt:
        base_map = {
            "goes": "go",
            "studies": "study",
            "has": "have",
            "works": "work",
            "likes": "like",
            "plays": "play",
            "does": "do",
        }
        subj = m_doesnt.group(1)
        bad_v = m_doesnt.group(2).lower()
        base_v = base_map.get(bad_v, bad_v)
        recast = re.sub(
            re.escape(m_doesnt.group(0)),
            f"{subj} doesn't {base_v}",
            msg,
            count=1,
            flags=re.IGNORECASE,
        )
        return (
            recast,
            f"Después de doesn't el verbo vuelve a su forma base: usa '{subj} doesn't {base_v}'.",
            f"{subj.capitalize()} doesn't {base_v} on weekends.",
        )

    for pattern, repl, why_es, example_en in _L1_ES_RECAST_RULES:
        if pattern.search(msg):
            recast = pattern.sub(repl, msg, count=1)
            return (recast, why_es, example_en)

    return (None, None, None)


def _compute_fallback_missions_completed(
    history: list[dict[str, str]],
    message: str,
    turn_index: int,
) -> list[int]:
    user_msgs = [
        str(h.get("content") or "").strip()
        for h in history
        if str(h.get("role") or "").lower() == "user" and str(h.get("content") or "").strip()
    ]
    if message.strip():
        user_msgs.append(message.strip())

    completed: set[int] = set()
    substantive = [m for m in user_msgs if len(_norm_en_tokens(m)) >= 3]
    if len(substantive) >= 1 or turn_index >= 1:
        completed.add(0)
    if (
        len(substantive) >= 2
        or any(
            re.search(r"\b(don't|doesn't|not|never|some|any|there\s+are|but)\b", m, re.IGNORECASE)
            for m in user_msgs
        )
    ):
        completed.add(1)
    if (
        len(substantive) >= 3
        or any(
            "?" in m
            or re.match(r"^\s*(do|does|is|are|what|where|when|how)\b", m, re.IGNORECASE)
            for m in user_msgs
        )
    ):
        completed.add(2)
    return sorted(completed)


def _build_language_session_summary(
    *,
    node_title: str,
    history: list[dict[str, str]],
    message: str,
) -> dict[str, Any]:
    user_msgs = [
        str(h.get("content") or "").strip()
        for h in history
        if str(h.get("role") or "").lower() == "user" and str(h.get("content") or "").strip()
    ]
    if message.strip() and (not user_msgs or user_msgs[-1] != message.strip()):
        user_msgs.append(message.strip())

    items: list[dict[str, str]] = []
    seen_said: set[str] = set()

    for utt in user_msgs:
        if utt.lower() in seen_said:
            continue
        recast, why_es, _example = _detect_l1_es_recast(utt)
        if recast and why_es:
            items.append({"said": utt, "better": recast, "why": why_es})
            seen_said.add(utt.lower())
        elif len(items) < 2 and len(_norm_en_tokens(utt)) >= 2:
            polished = utt[0].upper() + utt[1:] if utt else utt
            if polished and polished[-1] not in ".!?":
                polished += "."
            items.append(
                {
                    "said": utt,
                    "better": polished,
                    "why": "Buena producción en inglés; mantén mayúscula inicial, puntuación y orden Sujeto + Verbo.",
                }
            )
            seen_said.add(utt.lower())
        if len(items) >= 3:
            break

    fallback_pairs = [
        {
            "said": "She don't study on Mondays.",
            "better": "She doesn't study on Mondays.",
            "why": "En 3.ª persona singular (he/she/it) el auxiliar negativo es doesn't + verbo base.",
        },
        {
            "said": "There is many books on the desk.",
            "better": "There are many books on the desk.",
            "why": "Con sustantivos plurales contables siempre usamos 'there are'.",
        },
        {
            "said": "Is very important to practice every day.",
            "better": "It is very important to practice every day.",
            "why": "En inglés no se omite el sujeto: iniciamos con el pronombre 'It'.",
        },
    ]
    for fp in fallback_pairs:
        if len(items) >= 2:
            break
        items.append(fp)

    return {
        "headline": f"Resumen de tu práctica guiada en {node_title}",
        "items": items[:3],
    }


def _sanitize_session_summary(
    raw_summary: Any,
    *,
    node_title: str,
    history: list[dict[str, str]],
    message: str,
) -> dict[str, Any]:
    if isinstance(raw_summary, dict):
        headline = str(raw_summary.get("headline") or "").strip()
        raw_items = raw_summary.get("items")
        clean_items: list[dict[str, str]] = []
        if isinstance(raw_items, list):
            for it in raw_items[:3]:
                if isinstance(it, dict):
                    said = str(it.get("said") or "").strip()
                    better = str(it.get("better") or "").strip()
                    why = str(it.get("why") or "").strip()
                    if said and better and why:
                        clean_items.append({"said": said, "better": better, "why": why})
        if len(clean_items) >= 2:
            return {
                "headline": headline or f"Resumen de tu práctica en {node_title}",
                "items": clean_items,
            }
    return _build_language_session_summary(
        node_title=node_title,
        history=history,
        message=message,
    )


def _fallback_language_practice_chat(
    *,
    node_title: str,
    node_summary: str,
    message: str,
    history: list[dict[str, str]],
    missions: list[str],
    turn_index: int,
    start: bool,
    finish: bool,
) -> dict[str, Any]:
    active_missions = [str(m).strip() for m in missions if str(m).strip()][:3]
    if len(active_missions) < 3:
        defaults = _default_language_missions(node_title, node_summary)
        for d in defaults:
            if len(active_missions) >= 3:
                break
            if d not in active_missions:
                active_missions.append(d)

    chips = _default_lexical_chips(node_title, node_summary)

    if start:
        ctx = f"{node_title} {node_summary}".lower()
        if any(k in ctx for k in ("there is", "there are", "quantifier", "countable")):
            reply_en = "Hi! Let's practice English together. What is on your desk right now?"
            translation_es = "¡Hola! Practiquemos inglés juntos. ¿Qué hay sobre tu escritorio ahora mismo?"
            example_en = "There is a notebook and there are two pens on my desk."
            starter = "There is a ... and there are ..."
        else:
            reply_en = "Hi! Let's practice English together. What do you usually do every morning before classes?"
            translation_es = "¡Hola! Practiquemos inglés juntos. ¿Qué haces normalmente cada mañana antes de clases?"
            example_en = "I usually wake up at seven and review my notes."
            starter = "I usually ..."
        return {
            "reply_en": _cap_en_words(reply_en, 25),
            "translation_es": translation_es,
            "inline_correction_es": None,
            "example_en": example_en,
            "missions": active_missions,
            "missions_completed": [],
            "lexical_chips": chips[:6],
            "sentence_starter": starter,
            "session_summary": None,
            "provider": "local_fallback",
        }

    completed = _compute_fallback_missions_completed(history, message, turn_index)

    if finish:
        summary = _build_language_session_summary(
            node_title=node_title,
            history=history,
            message=message,
        )
        return {
            "reply_en": _cap_en_words(
                "Great work today! You practiced natural English sentences and completed your session. See you next time!",
                25,
            ),
            "translation_es": "¡Excelente trabajo hoy! Practicaste oraciones naturales en inglés y completaste tu sesión. ¡Hasta la próxima!",
            "inline_correction_es": None,
            "example_en": summary["items"][0]["better"] if summary["items"] else "She studies English every day.",
            "missions": active_missions,
            "missions_completed": completed,
            "lexical_chips": chips[:5],
            "sentence_starter": None,
            "session_summary": summary,
            "provider": "local_fallback",
        }

    recast, why_es, example_en = _detect_l1_es_recast(message)
    next_missing = next((i for i in (0, 1, 2) if i not in completed), None)

    if recast and why_es:
        follow_q = (
            "What do you never do on weekends?"
            if next_missing == 1
            else ("Can you ask me one question using Do or Does?" if next_missing == 2 else "Tell me one more detail!")
        )
        reply_en = _cap_en_words(f"Nice try! You mean **{recast}**. {follow_q}", 25)
        translation_es = f"¡Buen intento! Quieres decir «{recast}». Continúa con la siguiente misión."
        inline_corr: str | None = why_es
    else:
        if next_missing == 1:
            reply_en = _cap_en_words(
                "Great! You **expressed that clearly**. Now, what is something you **don't do** on weekends?",
                25,
            )
            translation_es = "¡Genial! Lo expresaste con claridad. Ahora, ¿qué es algo que no haces los fines de semana?"
        elif next_missing == 2:
            reply_en = _cap_en_words(
                "Awesome! That sounds **very natural**. Can you **ask me a question** in English now?",
                25,
            )
            translation_es = "¡Excelente! Eso suena muy natural. ¿Puedes hacerme una pregunta en inglés ahora?"
        else:
            reply_en = _cap_en_words(
                "Well done! You **completed all three missions** in English. Ready to see your summary?",
                25,
            )
            translation_es = "¡Bien hecho! Completaste las tres misiones en inglés. ¿Listo para ver tu resumen?"
        inline_corr = None
        example_en = example_en or "On weekends, I don't have early classes, so I review vocabulary."

    if next_missing == 1:
        starter = "On weekends, I don't ..."
    elif next_missing == 2:
        starter = "Do you usually ...?"
    else:
        starter = "I also like to ..."

    should_summarize = len(completed) >= 3 or turn_index >= 5
    summary = (
        _build_language_session_summary(node_title=node_title, history=history, message=message)
        if should_summarize
        else None
    )

    return {
        "reply_en": reply_en,
        "translation_es": translation_es,
        "inline_correction_es": inline_corr,
        "example_en": example_en,
        "missions": active_missions,
        "missions_completed": completed,
        "lexical_chips": chips[:6],
        "sentence_starter": starter,
        "session_summary": summary,
        "provider": "local_fallback",
    }


def run_language_practice_chat_with_ai(
    *,
    course_title: str,
    node_title: str,
    node_summary: str,
    story_script: str,
    message: str = "",
    history: list[dict[str, str]] | None = None,
    missions: list[str] | None = None,
    turn_index: int = 0,
    start: bool = False,
    finish: bool = False,
    preferred_provider: str = "auto",
) -> dict[str, Any]:
    """Ejecuta un turno de practica conversacional guiada de ingles (A1-A2) con Salient Recasts y 3 misiones."""
    hist = list(history or [])
    existing_missions = [str(m).strip() for m in (missions or []) if str(m).strip()]

    fallback_res = _fallback_language_practice_chat(
        node_title=node_title,
        node_summary=node_summary,
        message=message,
        history=hist,
        missions=existing_missions,
        turn_index=turn_index,
        start=start,
        finish=finish,
    )

    mode_str = "start" if start else ("finish" if finish else "turn")
    system_prompt = (
        "Eres un tutor conversacional de ingles A1-A2 de Brotal (`language_studio`) para estudiantes universitarios "
        "hispanohablantes.\n"
        "REGLAS ESTRICTAS:\n"
        "1. `reply_en`: SIEMPRE en ingles claro nivel A1-A2 y BREVE (MAXIMO 25 PALABRAS). "
        "En turnos intermedios aplica **Salient Recasts**: incorpora la forma corregida o natural en **negrita** (`**...**`) "
        "dentro de la respuesta conversacional.\n"
        "2. `translation_es`: traduccion natural al espanol de `reply_en`.\n"
        "3. `missions`: SIEMPRE exactamente 3 misiones comunicativas concretas derivadas del nodo.\n"
        "4. `missions_completed`: lista ordenada de indices enteros en [0, 1, 2] ya logrados considerando todo `history` + `message` "
        "(nunca retroceder misiones ya logradas; en `start=true` devolver `[]`).\n"
        "5. `inline_correction_es`: explicacion breve en espanol (1 linea) SOLO si el estudiante cometio un error real "
        "(ej. interferencia espanol->ingles); `null` si la frase estuvo bien o si `start=true`/`finish=true`.\n"
        "6. `lexical_chips`: entre 4 y 6 palabras o frases cortas utiles en ingles para ayudar en el siguiente turno.\n"
        "7. `sentence_starter`: inicio de oracion en ingles (ej. `'I usually ...'`) o `null` si `finish=true`.\n"
        "8. `session_summary`: OBLIGATORIO cuando `finish=true` (y recomendado si se completaron las 3 misiones o `turn_index >= 5`): "
        "`{\"headline\": \"...\", \"items\": [{\"said\": \"...\", \"better\": \"...\", \"why\": \"...\"}]}` con 2 a 3 pares reales "
        "basados en los mensajes del usuario en `history` (o ejemplos clave del nodo si hubo pocos turnos). `null` en `start=true`.\n"
        "9. PROHIBIDO usar emojis.\n"
        "Responde UNICAMENTE JSON valido con claves: `reply_en`, `translation_es`, `inline_correction_es`, `example_en`, "
        "`missions`, `missions_completed`, `lexical_chips`, `sentence_starter`, `session_summary`."
    )

    user_payload = {
        "mode": mode_str,
        "course_title": course_title,
        "node_title": node_title,
        "node_summary": node_summary,
        "story_context": story_script[:1200],
        "missions": existing_missions or fallback_res["missions"],
        "turn_index": turn_index,
        "history": hist[-12:],
        "message": message,
    }

    try:
        comp = complete_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            preferred_provider=preferred_provider,
            json_mode=True,
            temperature=0.4,
            max_tokens=900,
        )
        parsed = extract_json_object(comp.text)

        reply_en = _cap_en_words(str(parsed.get("reply_en") or fallback_res["reply_en"]), 25)
        translation_es = str(parsed.get("translation_es") or "").strip() or str(fallback_res["translation_es"])

        raw_corr = parsed.get("inline_correction_es")
        inline_correction_es = (
            str(raw_corr).strip() or None
            if (isinstance(raw_corr, str) and not start and not finish)
            else None
        )

        raw_example = parsed.get("example_en")
        example_en = (
            str(raw_example).strip() or None
            if isinstance(raw_example, str)
            else fallback_res["example_en"]
        )

        raw_missions = parsed.get("missions")
        clean_missions = (
            [str(m).strip() for m in raw_missions if str(m).strip()][:3]
            if isinstance(raw_missions, list)
            else []
        )
        if len(clean_missions) < 3:
            for fm in fallback_res["missions"]:
                if len(clean_missions) >= 3:
                    break
                if fm not in clean_missions:
                    clean_missions.append(fm)

        if start:
            missions_completed: list[int] = []
        else:
            raw_done = parsed.get("missions_completed")
            ai_done = {
                int(x)
                for x in (raw_done if isinstance(raw_done, list) else [])
                if isinstance(x, int) and 0 <= x <= 2
            }
            fb_done = set(fallback_res["missions_completed"])
            missions_completed = sorted(ai_done | fb_done)

        raw_chips = parsed.get("lexical_chips")
        lexical_chips = (
            [str(c).strip() for c in raw_chips if str(c).strip()][:6]
            if isinstance(raw_chips, list)
            else []
        )
        if len(lexical_chips) < 4:
            for fc in fallback_res["lexical_chips"]:
                if len(lexical_chips) >= 4:
                    break
                if fc not in lexical_chips:
                    lexical_chips.append(fc)

        raw_starter = parsed.get("sentence_starter")
        sentence_starter = (
            None
            if finish
            else (str(raw_starter).strip() or fallback_res["sentence_starter"])
        )

        if start:
            session_summary: dict[str, Any] | None = None
        elif finish or len(missions_completed) >= 3 or turn_index >= 5 or parsed.get("session_summary"):
            session_summary = _sanitize_session_summary(
                parsed.get("session_summary"),
                node_title=node_title,
                history=hist,
                message=message,
            )
        else:
            session_summary = None

        return {
            "reply_en": reply_en,
            "translation_es": translation_es,
            "inline_correction_es": inline_correction_es,
            "example_en": example_en,
            "missions": clean_missions,
            "missions_completed": missions_completed,
            "lexical_chips": lexical_chips,
            "sentence_starter": sentence_starter,
            "session_summary": session_summary,
            "provider": comp.provider,
        }
    except (AiProviderError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return fallback_res
