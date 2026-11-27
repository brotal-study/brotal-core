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

        # Si es reto de codigo no aprobado y no vinieron code_fixes del proveedor, generar guia puntual
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
        elif corrected_solution is None and status != "passed" and r_points:
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
    """
    rubric_spec: list[dict[str, Any]] = []
    all_keys: list[str] = []
    has_code_challenge = engine_type == "code_lab"

    for q in eval_prompts:
        qid = str(q["id"])
        ct = str(q.get("challenge_type") or "concept").strip().lower()
        lang = str(q.get("language") or "text").strip().lower()
        starter = q.get("starter_code")
        if ct in ("debug", "implement", "trace") or starter:
            has_code_challenge = True
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
        rubric_spec.append(item_spec)

    senior_dev_rules = ""
    if has_code_challenge:
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
    is_code_lab = engine_type == "code_lab" or any(
        str(q.get("challenge_type") or "concept") in ("debug", "implement", "trace") or q.get("starter_code")
        for q in eval_prompts
    )
    inferred_lang = next(
        (
            str(q.get("language")).strip().lower()
            for q in eval_prompts
            if str(q.get("language") or "").strip().lower() in ("java", "sql", "python", "c")
        ),
        "java" if is_code_lab else "text",
    )
    metaphor_hint = world_metaphor or f"Taller practico de {course_title}"
    style_rule = explanation_style_instruction(explanation_style, metaphor_hint)

    code_lab_story_rule = ""
    if is_code_lab:
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
            "de prosa (y el bloque de codigo cercado si es `code_lab`)."
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
    is_code_lab = engine_type == "code_lab" or any(
        str(p.get("challenge_type") or "concept") in ("debug", "implement", "trace") or p.get("starter_code")
        for p in source_prompts
    )
    inferred_lang = next(
        (
            str(p.get("language"))
            for p in source_prompts
            if str(p.get("language") or "") in ("java", "sql", "python", "c")
        ),
        "java" if is_code_lab else "text",
    )

    code_lab_regen_rule = ""
    if is_code_lab:
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
            ct = raw_ct if raw_ct in ("concept", "trace", "debug", "implement") else orig_ct
            lang = str(ai_item.get("language") or orig.get("language") or inferred_lang).strip().lower()
            if lang not in ("java", "sql", "python", "c", "text"):
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

            updated.append(
                {
                    "id": qid,
                    "question": clean_q,
                    "rubric_points": pts,
                    "challenge_type": ct,
                    "language": lang,
                    "starter_code": clean_starter,
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
            tpl = templates[idx % len(templates)]
            new_q = tpl.format(metaphor=metaphor_hint, node=node_title, course=course_title, focus=focus)
            if new_q == prev_q:
                new_q = templates[(idx + 1) % len(templates)].format(
                    metaphor=metaphor_hint,
                    node=node_title,
                    course=course_title,
                    focus=focus,
                )
            ct = str(orig.get("challenge_type") or "concept").strip().lower()
            if ct not in ("concept", "trace", "debug", "implement"):
                ct = "concept"
            lang = str(orig.get("language") or inferred_lang).strip().lower()
            if lang not in ("java", "sql", "python", "c", "text"):
                lang = inferred_lang
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
            updated_fallback.append(
                {
                    "id": qid,
                    "question": clean_q,
                    "rubric_points": pts,
                    "challenge_type": ct,
                    "language": lang,
                    "starter_code": clean_starter,
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
