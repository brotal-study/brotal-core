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
            "- Si `score < 7.0`, en `re_explanation` incluye una explicacion directa del fallo acompañada de un "
            "bloque de codigo Markdown limpio (ej. ```java ... ``` o ```sql ... ```) mostrando la correccion o guia.\n"
        )

    system_prompt = (
        "Eres el Evaluador Socratico de Brotal. Evaluas respuestas a ciegas de un estudiante universitario "
        "con rigor del 1.0 al 10.0 (7.0 o mas aprueba). No regales puntos si la respuesta es vaga o vacia."
        f"{senior_dev_rules}\n"
        "Responde UNICAMENTE un objeto JSON valido con esta estructura exacta:\n"
        "{\n"
        '  "score": 7.5,\n'
        '  "covered_points": ["q1::0", "q1::1"],\n'
        '  "imprecisions": ["En linea X: falta validar null / usar equals() en vez de =="],\n'
        '  "re_explanation": "Breve re-explicacion conversada y bloque de codigo Markdown si aplica (solo si score < 7.0, vacio si >= 7.0)"\n'
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


evaluate_answers_with_ai = evaluate_with_ai


def _strip_bullets(story: str) -> str:
    lines = story.splitlines()
    cleaned_lines: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            cleaned_lines.append("")
            continue
        s = re.sub(r"^[-*•]\s+", "", s)
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
) -> tuple[str, str]:
    """Genera una explicacion alternativa respetando explanation_style ('narrative' | 'direct' | 'structured').

    Siempre 2 a 3 parrafos continuos (~180-240 palabras en total), sin listas con vinetas.
    Si no hay IA configurada, genera una version determinista alternativa segun el estilo elegido.
    Devuelve (new_story_script, provider_used).
    """
    rubric_points = [
        pt
        for q in eval_prompts
        for pt in q.get("rubric_points", [])
    ]
    metaphor_hint = world_metaphor or f"Taller practico de {course_title}"
    style_rule = explanation_style_instruction(explanation_style, metaphor_hint)

    try:
        system_prompt = (
            "Eres el autor pedagogico de Brotal. Tu tarea es explicar un concepto universitario "
            "en espanol en 2 a 3 parrafos continuos (~180 a 240 palabras en total).\n"
            f"{style_rule}\n"
            "PROHIBIDO usar listas con vinetas, numeraciones o encabezados markdown: entrega unicamente los 2 a 3 parrafos "
            "que cubran todos los conceptos clave de la rubrica."
        )
        user_prompt = (
            f"Ramo: {course_title}\n"
            f"Estilo solicitado: {explanation_style}\n"
            f"Metafora del mundo (solo si el estilo es narrative): {metaphor_hint}\n"
            f"Nodo: {node_title} ({node_summary})\n"
            f"Conceptos que deben quedar claros: {', '.join(rubric_points)}\n"
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
        if explanation_style == "direct":
            alt = _strip_bullets(
                f"{node_title} en {course_title} define un mecanismo tecnico fundamental cuyo objetivo directo es "
                f"resolver: {node_summary}. Su operacion se basa en reglas verificables que determinan el comportamiento "
                f"exacto del sistema sin ambiguedades.\n\n"
                f"En terminos técnicos, el funcionamiento exige cumplir que {concepts_prose}. Cada parametro y condicion "
                f"afecta de forma directa la eficiencia, correccion y estabilidad de la implementacion.\n\n"
                f"Para validar {node_title} en la practica, se comprueba directamente que se cumplan estas propiedades "
                f"tecnicas ante entradas normales y casos de borde."
            )
        elif explanation_style == "structured":
            alt = _strip_bullets(
                f"Concepto central: {node_title} dentro de {course_title} establece la base estructural para abordar "
                f"{node_summary}, definiendo los limites y responsabilidades del componente en el sistema.\n\n"
                f"Causa y efecto: El mecanismo opera garantizando que {concepts_prose}. Cuando una de estas condiciones "
                f"varia, el efecto directo se propaga sobre el rendimiento y la consistencia del resultado.\n\n"
                f"Ejemplo concreto: En una implementacion real de {course_title}, aplicar {node_title} permite verificar "
                f"paso a paso cada criterio tecnico y diagnosticar con exactitud cualquier desviacion."
            )
        else:
            alt = _strip_bullets(
                f"Miralo ahora desde otro angulo operativo dentro de {metaphor_hint}. Cuando nos enfrentamos a {node_title} "
                f"en {course_title}, el error tipico es quedarse en la definicion de memoria en vez de seguir el flujo real "
                f"del sistema y entender que problema concreto resuelve: {node_summary}.\n\n"
                f"Imagina que tienes que diagnosticarlo en vivo paso a paso cuando algo falla en {metaphor_hint}: primero "
                f"confirmas la causa y efecto verificando que {concepts_prose}. Cada una de estas piezas cumple un rol "
                f"especifico para mantener la estabilidad del diseno.\n\n"
                f"Al conectar cada mecanismo con su consecuencia practica dentro de {metaphor_hint}, ya no necesitas "
                f"memorizar definiciones aisladas, porque puedes anticipar que ocurre si una condicion cambia y justificar "
                f"tu decision tecnica con claridad."
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
            (
                f"// Variante A (Implementacion): {node_title}\n"
                "import java.util.List;\n\n"
                f"public class {clean_cls}Analyzer {{\n"
                "    /**\n"
                "     * Calcula el promedio de los valores positivos de la lista.\n"
                "     * Si la lista es null o no contiene positivos, retorna 0.0.\n"
                "     */\n"
                "    public double promedioPositivos(List<Integer> valores) {\n"
                "        // TODO: implementar validando null y filtrando valores > 0\n"
                "        return 0.0;\n"
                "    }\n"
                "}"
            ),
            (
                f"// Variante B (Implementacion): {node_title}\n"
                "import java.util.Map;\n\n"
                f"public class {clean_cls}Registry {{\n"
                "    /**\n"
                "     * Incrementa en 1 el contador asociado a 'id' dentro del mapa.\n"
                "     * Si 'id' es null o vacio lanza IllegalArgumentException.\n"
                "     */\n"
                "    public int registrarEvento(Map<String, Integer> contadores, String id) {\n"
                "        // TODO: implementar actualizacion segura en el mapa y retornar nuevo total\n"
                "        return 0;\n"
                "    }\n"
                "}"
            ),
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
            f"\n4. MODO `code_lab` ACTIVO (lenguaje `{inferred_lang}`): Manten o varia los tipos de reto "
            "(`\"challenge_type\": \"debug\" | \"implement\" | \"trace\" | \"concept\"`, "
            f"`\"language\": \"{inferred_lang}\"`) y genera un NUEVO `starter_code` COMPLETAMENTE DISTINTO "
            "al anterior para cada pregunta de codigo (`debug`, `implement`, `trace`).\n"
        )

    try:
        system_prompt = (
            "Eres el Evaluador Socratico de Brotal. Tu tarea es redactar PREGUNTAS NUEVAS Y DISTINTAS "
            "que evaluen EXACTAMENTE los mismos `rubric_points` de cada pregunta original.\n"
            f"{q_rule}\n"
            "REGLAS OBLIGATORIAS:\n"
            "1. Conserva los mismos `id` y los mismos `rubric_points` de cada item.\n"
            "2. Cambia por completo la formulacion de cada `question` respetando el estilo solicitado.\n"
            "3. Responde UNICAMENTE un objeto JSON valido con la clave `eval_prompts`:\n"
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
            if isinstance(raw_starter, str) and raw_starter.strip():
                starter = raw_starter.strip()

            if ct in ("debug", "implement", "trace"):
                prev_starter = str(orig.get("starter_code") or "").strip() or None
                if not starter or (prev_starter and starter == prev_starter):
                    starter = _alternate_starter_code(
                        language=lang,
                        challenge_type=ct,
                        node_title=node_title,
                        prev_starter=prev_starter,
                        idx=idx + 1,
                    )

            updated.append(
                {
                    "id": qid,
                    "question": candidate_q,
                    "rubric_points": pts,
                    "challenge_type": ct,
                    "language": lang,
                    "starter_code": starter if ct in ("debug", "implement", "trace") else None,
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
            updated_fallback.append(
                {
                    "id": qid,
                    "question": new_q,
                    "rubric_points": pts,
                    "challenge_type": ct,
                    "language": lang,
                    "starter_code": starter,
                }
            )
        return (updated_fallback, "local_fallback")
