"""Ingesta local de apuntes BYOF (PDF, PPTX, DOCX, MD, TXT) -> FTS5 -> Arbol de Estudio (v1.0).

Contrato:
- Extrae texto por pagina / diapositiva / seccion sin PyTorch.
- Indexa cada seccion en `local_chunks_fts` (SQLite FTS5).
- Usa `ai_router.py` para generar un arbol real de 6..12 nodos (`theory` + `practice`) con historias
  conversadas continuas (sin listas secas) y `eval_prompts` con `rubric_points`.
- Si no hay API key externa o el LLM devuelve menos de 6 nodos, completa/construye un arbol valido de
  6..12 nodos a partir de los chunks reales extraidos para que nunca falle offline.
- Guarda el ramo como `active` en SQLite listo para estudiar al instante.
- Los archivos originales nunca se guardan en pack_metadata_json ni se exportan en un Course Pack.
"""
from __future__ import annotations

import io
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.schemas.pack import CoursePack, PackMetadata
from app.services import ai_router
from app.services.ai_router import (
    AiProviderError,
    _fallback_story_code_block,
    explanation_style_instruction,
    extract_json_object,
    question_style_instruction,
    sanitize_code_prompt,
)
from app.services.pack_manager import (
    append_nodes_to_course,
    install_pack,
    resolve_course_row,
)

ALLOWED_EXTENSIONS = {".pdf", ".pptx", ".docx", ".md", ".txt"}
_SEPARATOR_LINE_RE = re.compile(r"(?m)^\s*(?:[-*_]{3,}|={3,})\s*$")


@dataclass
class ExtractedChunk:
    source_file: str
    section_title: str
    content: str


_JAVA_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\bpublic\s+class\b", re.IGNORECASE), 4),
    (re.compile(r"\b(?:public|private|protected)\s+static\s+void\s+main\b", re.IGNORECASE), 5),
    (re.compile(r"\bvoid\s+main\b", re.IGNORECASE), 3),
    (re.compile(r"\bextends\s+[A-Z]\w*"), 3),
    (re.compile(r"\bimplements\s+[A-Z]\w*"), 3),
    (re.compile(r"@Override\b"), 4),
    (re.compile(r"\bSystem\.out\.print"), 4),
    (re.compile(r"\btry\s*\{"), 3),
    (re.compile(r"\bcatch\s*\("), 3),
    (re.compile(r"\b(?:ArrayList|HashMap|LinkedList|List|Map)<"), 3),
    (re.compile(r"\b(?:java|jvm|inf2236)\b", re.IGNORECASE), 3),
]

_SQL_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\bSELECT\b[\s\S]{1,120}\bFROM\b", re.IGNORECASE), 5),
    (re.compile(r"\bCREATE\s+TABLE\b", re.IGNORECASE), 5),
    (re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE), 4),
    (re.compile(r"\b(?:INNER|LEFT|RIGHT)\s+JOIN\b", re.IGNORECASE), 4),
    (re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE), 3),
    (re.compile(r"\bPRIMARY\s+KEY\b", re.IGNORECASE), 3),
    (re.compile(r"\bFOREIGN\s+KEY\b", re.IGNORECASE), 3),
    (re.compile(r"\b(?:sql|postgresql|mysql|sqlite|base\s+de\s+datos|bases\s+de\s+datos)\b", re.IGNORECASE), 4),
]

_PYTHON_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"(?m)^\s*def\s+[a-zA-Z_]\w*\s*\("), 5),
    (re.compile(r"\bdef\s+[a-zA-Z_]\w*\s*\("), 3),
    (re.compile(r"\b__init__\s*\("), 5),
    (re.compile(r"\bself\.[a-zA-Z_]\w*"), 4),
    (re.compile(r"(?m)^\s*elif\s+.+:"), 4),
    (re.compile(r"\bpython\b", re.IGNORECASE), 4),
]

_C_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"#include\s*<[\w.]+>"), 5),
    (re.compile(r"\bint\s+main\s*\("), 4),
    (re.compile(r"\b(?:printf|scanf|malloc|free|sizeof)\s*\("), 4),
    (re.compile(r"\btypedef\s+struct\b"), 4),
    (re.compile(r"\b(?:lenguaje\s+c|c\+\+|punteros\s+en\s+c)\b", re.IGNORECASE), 4),
]

_GENERIC_CODE_TITLE_RE = re.compile(
    r"\b(?:programaci[oó]n|algoritmos?|estructuras?\s+de\s+datos|bases?\s+de\s+datos|java|sql|python|poo|orientada\s+a\s+objetos)\b",
    re.IGNORECASE,
)


def detect_engine_type(
    course_code: str,
    title: str,
    chunks: list[ExtractedChunk] | list[Any],
) -> tuple[str, str]:
    """Detecta de forma liviana si el ramo corresponde a ('code_lab', lang) o ('concept_tree', 'text')."""
    header_text = f"{course_code} {title}".strip()
    chunk_parts: list[str] = []
    for ch in chunks[:40]:
        if isinstance(ch, ExtractedChunk):
            chunk_parts.append(f"{ch.section_title}\n{ch.content[:1500]}")
        elif isinstance(ch, dict):
            chunk_parts.append(f"{ch.get('section_title', '')}\n{str(ch.get('content', ''))[:1500]}")
        else:
            chunk_parts.append(str(ch)[:1500])

    body_text = "\n".join(chunk_parts)
    combined = f"{header_text}\n{body_text}"

    scores: dict[str, int] = {"java": 0, "sql": 0, "python": 0, "c": 0}

    for pat, weight in _JAVA_PATTERNS:
        matches = len(pat.findall(combined))
        if matches:
            scores["java"] += weight * min(matches, 4)
        if pat.search(header_text):
            scores["java"] += weight * 2

    for pat, weight in _SQL_PATTERNS:
        matches = len(pat.findall(combined))
        if matches:
            scores["sql"] += weight * min(matches, 4)
        if pat.search(header_text):
            scores["sql"] += weight * 2

    for pat, weight in _PYTHON_PATTERNS:
        matches = len(pat.findall(combined))
        if matches:
            scores["python"] += weight * min(matches, 4)
        if pat.search(header_text):
            scores["python"] += weight * 2

    for pat, weight in _C_PATTERNS:
        matches = len(pat.findall(combined))
        if matches:
            scores["c"] += weight * min(matches, 4)
        if pat.search(header_text):
            scores["c"] += weight * 2

    best_lang, best_score = max(scores.items(), key=lambda kv: kv[1])
    has_title_signal = bool(_GENERIC_CODE_TITLE_RE.search(header_text))
    has_body_title_signal = len(_GENERIC_CODE_TITLE_RE.findall(body_text)) >= 2

    if best_score >= 4 or has_title_signal or (best_score >= 3 and has_body_title_signal):
        if best_score == 0:
            low_header = header_text.lower()
            if "sql" in low_header or "base de datos" in low_header or "bases de datos" in low_header:
                best_lang = "sql"
            elif "python" in low_header:
                best_lang = "python"
            elif "estructura de datos" in low_header or "estructuras de datos" in low_header:
                best_lang = "c" if " c " in f" {low_header} " else "java"
            else:
                best_lang = "java"
        return ("code_lab", best_lang)

    return ("concept_tree", "text")


def _fallback_starter_code(
    *,
    language: str,
    challenge_type: str,
    node_title: str,
    index: int = 1,
) -> str:
    """Genera un starter_code realista y autocontenido segun lenguaje y tipo de desafio."""
    lang = language if language in ("java", "sql", "python", "c") else "java"
    clean_cls = re.sub(r"[^a-zA-Z0-9]", "", node_title.title())[:18] or f"Modulo{index}"
    if not clean_cls[0].isalpha():
        clean_cls = f"Clase{clean_cls}"

    if lang == "sql":
        if challenge_type == "debug":
            return (
                f"-- Caso: {node_title}\n"
                "-- BUG: La consulta intenta filtrar una agregacion con WHERE y omite GROUP BY.\n"
                "SELECT c.id_curso, c.nombre, COUNT(i.id_estudiante) AS total_inscritos\n"
                "FROM cursos c\n"
                "INNER JOIN inscripciones i ON c.id_curso = i.id_curso\n"
                "WHERE COUNT(i.id_estudiante) >= 5\n"
                "ORDER BY total_inscritos DESC;"
            )
        if challenge_type == "trace":
            return (
                f"-- Traza SQL: {node_title}\n"
                "SELECT d.nombre_depto, COUNT(e.id) AS activos, AVG(e.puntaje) AS promedio\n"
                "FROM departamentos d\n"
                "LEFT JOIN estudiantes e ON e.depto_id = d.id AND e.activo = 1\n"
                "GROUP BY d.id, d.nombre_depto\n"
                "HAVING COUNT(e.id) >= 0\n"
                "ORDER BY activos DESC;"
            )
        return "-- Implementa tu consulta SQL aquí"

    if lang == "python":
        if challenge_type == "debug":
            return (
                f"# Modulo: {node_title}\n"
                "def procesar_registros(items: list[int], umbral: int = 0) -> list[int]:\n"
                "    # BUG: mutar la lista mientras se itera sobre ella salta elementos\n"
                "    for idx, valor in enumerate(items):\n"
                "        if valor < umbral:\n"
                "            items.remove(valor)\n"
                "    return items\n"
            )
        if challenge_type == "trace":
            return (
                f"# Traza paso a paso: {node_title}\n"
                "def acumular(valores: list[int]) -> dict[str, int]:\n"
                "    estado = {'pares': 0, 'impares': 0}\n"
                "    for v in valores:\n"
                "        clave = 'pares' if v % 2 == 0 else 'impares'\n"
                "        estado[clave] += v\n"
                "    return estado\n\n"
                "print(acumular([2, 3, 4, 5]))\n"
            )
        return "# Implementa tu solución en Python aquí"

    if lang == "c":
        if challenge_type == "debug":
            return (
                f"/* Modulo: {node_title} */\n"
                "#include <stdio.h>\n\n"
                "int sumar_arreglo(const int *arr, int n) {\n"
                "    int total = 0;\n"
                "    /* BUG: condicion de borde i <= n accede fuera de limites */\n"
                "    for (int i = 0; i <= n; i++) {\n"
                "        total += arr[i];\n"
                "    }\n"
                "    return total;\n"
                "}\n"
            )
        if challenge_type == "trace":
            return (
                f"/* Traza de ejecucion: {node_title} */\n"
                "#include <stdio.h>\n\n"
                "int main(void) {\n"
                "    int datos[4] = {10, 20, 30, 40};\n"
                "    int *p = datos;\n"
                "    *(p + 2) += *p;\n"
                "    printf(\"%d %d\\n\", datos[0], datos[2]);\n"
                "    return 0;\n"
                "}\n"
            )
        return "/* Implementa tu solución en C aquí */"

    # Default: Java (INF2236 / POO)
    if challenge_type == "debug":
        return (
            f"// Contexto: {node_title}\n"
            "import java.util.List;\n\n"
            f"public class {clean_cls}Service {{\n"
            "    private int limiteMaximo;\n\n"
            f"    public {clean_cls}Service(int limiteMaximo) {{\n"
            "        // BUG 1: sombreamiento de atributo (falta this.limiteMaximo)\n"
            "        limiteMaximo = limiteMaximo;\n"
            "    }\n\n"
            "    public boolean validarCodigo(String codigo, List<String> registrados) {\n"
            "        // BUG 2: comparacion de Strings con == y posible NullPointerException\n"
            "        for (String actual : registrados) {\n"
            "            if (actual == codigo && actual.length() <= limiteMaximo) {\n"
            "                return true;\n"
            "            }\n"
            "        }\n"
            "        return false;\n"
            "    }\n"
            "}"
        )
    if challenge_type == "trace":
        return (
            f"// Traza de ejecucion en JVM: {node_title}\n"
            "class ComponenteBase {\n"
            "    protected int prioridad = 1;\n"
            "    public int calcular(int factor) {\n"
            "        return prioridad + factor;\n"
            "    }\n"
            "}\n\n"
            f"class {clean_cls} extends ComponenteBase {{\n"
            f"    public {clean_cls}() {{ this.prioridad = 3; }}\n"
            "    @Override\n"
            "    public int calcular(int factor) {\n"
            "        return super.calcular(factor) * 2;\n"
            "    }\n"
            "}\n\n"
            "// ¿Que imprime exactamente este bloque y por que?\n"
            f"ComponenteBase ref = new {clean_cls}();\n"
            "System.out.println(ref.calcular(4));"
        )
    return "// Implementa tu solución en Java aquí"


def _build_fallback_code_lab_prompts(
    *,
    branch: str,
    title: str,
    course_title: str,
    world_metaphor: str,
    question_style: str,
    key_phrases: list[str],
    default_language: str,
    node_index: int = 1,
) -> list[dict[str, Any]]:
    """Construye los eval_prompts de un nodo code_lab combinando teoria + practica de codigo real."""
    lang = default_language if default_language in ("java", "sql", "python", "c") else "java"
    lang_upper = lang.upper()
    q_concept = _build_fallback_question(
        question_style=question_style,
        title=title,
        course_title=course_title,
        world_metaphor=world_metaphor,
    )

    if branch == "practice":
        return [
            {
                "id": "q1",
                "question": (
                    f"[Debugging {lang_upper}] En este caso práctico de {title}, el siguiente código contiene "
                    "errores de lógica, referencias o invariantes. Corrige directamente el código para que cumpla "
                    "con la especificación."
                ),
                "rubric_points": [
                    f"Corrige los defectos del código aplicando los principios de {title}",
                    key_phrases[0][:160],
                ],
                "challenge_type": "debug",
                "language": lang,
                "starter_code": _fallback_starter_code(
                    language=lang,
                    challenge_type="debug",
                    node_title=title,
                    index=node_index,
                ),
            },
            {
                "id": "q2",
                "question": (
                    f"[Implementación {lang_upper}] Completa el método/consulta para resolver el requerimiento de "
                    f"{title} en {course_title}, respetando validaciones de borde y manejo de errores."
                ),
                "rubric_points": [
                    f"Implementa la lógica completa requerida para {title}",
                    key_phrases[1][:160],
                ],
                "challenge_type": "implement",
                "language": lang,
                "starter_code": _fallback_starter_code(
                    language=lang,
                    challenge_type="implement",
                    node_title=title,
                    index=node_index,
                ),
            },
        ]

    second_type = "trace" if node_index % 2 == 1 else "implement"
    second_question = (
        f"[Traza {lang_upper}] Analiza el siguiente fragmento sobre {title}, indica cuál es su salida exacta "
        "y explica paso a paso el flujo de ejecución en memoria."
        if second_type == "trace"
        else f"[Implementación {lang_upper}] Completa el esqueleto en {lang_upper} aplicando {title} y cuidando los casos borde."
    )

    return [
        {
            "id": "q1",
            "question": q_concept,
            "rubric_points": [p[:160] for p in key_phrases[:2]],
            "challenge_type": "concept",
            "language": lang,
            "starter_code": None,
        },
        {
            "id": "q2",
            "question": (
                f"[Debugging {lang_upper}] Revisa el siguiente código asociado a {title}, identifica el bug "
                "y edítalo directamente en el editor para corregirlo."
            ),
            "rubric_points": [
                f"Identifica y corrige el bug técnico en {title}",
                key_phrases[0][:160],
            ],
            "challenge_type": "debug",
            "language": lang,
            "starter_code": _fallback_starter_code(
                language=lang,
                challenge_type="debug",
                node_title=title,
                index=node_index,
            ),
        },
        {
            "id": "q3",
            "question": second_question,
            "rubric_points": [
                f"Explica o implementa con precisión el comportamiento de {title}",
                key_phrases[min(1, len(key_phrases) - 1)][:160],
            ],
            "challenge_type": second_type,
            "language": lang,
            "starter_code": _fallback_starter_code(
                language=lang,
                challenge_type=second_type,
                node_title=title,
                index=node_index,
            ),
        },
    ]


def _normalize_prompt_item(
    raw_prompt: dict[str, Any],
    *,
    p_idx: int,
    node_title: str,
    nid: str,
    engine_type: str,
    default_language: str,
) -> dict[str, Any]:
    """Normaliza un item de eval_prompts preservando challenge_type, language y starter_code."""
    pts = [str(x).strip() for x in (raw_prompt.get("rubric_points") or []) if str(x).strip()]
    if not pts:
        pts = [f"Explica los conceptos centrales de {node_title}"]

    raw_ct = str(raw_prompt.get("challenge_type") or "concept").strip().lower()
    challenge_type = raw_ct if raw_ct in ("concept", "trace", "debug", "implement") else "concept"

    raw_lang = str(raw_prompt.get("language") or "").strip().lower()
    if raw_lang in ("cpp", "c++"):
        raw_lang = "c"
    if raw_lang in ("java", "sql", "python", "c", "text"):
        language = raw_lang
    else:
        language = default_language if engine_type == "code_lab" else "text"

    starter_raw = raw_prompt.get("starter_code")
    if isinstance(starter_raw, str):
        starter_code: str | None = starter_raw.strip()
    else:
        starter_code = None

    if challenge_type in ("trace", "debug") and not starter_code:
        starter_code = _fallback_starter_code(
            language=language if language != "text" else default_language,
            challenge_type=challenge_type,
            node_title=node_title,
            index=p_idx,
        )
        if language == "text":
            language = default_language if default_language != "text" else "java"
    elif challenge_type == "implement":
        if starter_code is None:
            starter_code = _fallback_starter_code(
                language=language if language != "text" else default_language,
                challenge_type="implement",
                node_title=node_title,
                index=p_idx,
            )
        if language == "text":
            language = default_language if default_language != "text" else "java"

    raw_question = str(raw_prompt.get("question") or f"Explica con tus palabras {node_title or nid}.")
    clean_question, clean_starter = sanitize_code_prompt(raw_question, starter_code, language)

    return {
        "id": str(raw_prompt.get("id") or f"q{p_idx}"),
        "question": clean_question,
        "rubric_points": pts,
        "challenge_type": challenge_type,
        "language": language,
        "starter_code": clean_starter,
    }


def _is_valid_title(raw: str) -> bool:
    cleaned = re.sub(r"^[-=*_#:\s.]+|[-=*_#:\s.]+$", "", raw.strip())
    if not cleaned:
        return False
    return sum(1 for c in cleaned if c.isalnum()) >= 3


def _sanitize_title(raw: str, fallback: str) -> str:
    cleaned = re.sub(r"^[-=*_#:\s.]+|[-=*_#:\s.]+$", "", raw.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if sum(1 for c in cleaned if c.isalnum()) < 3:
        return fallback
    return cleaned


def _clean_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _SEPARATOR_LINE_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_chunks_from_bytes(filename: str, data: bytes) -> list[ExtractedChunk]:
    """Extrae secciones de texto desde .pdf, .pptx, .docx, .md o .txt."""
    safe_name = Path(filename).name
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Formato no soportado '{ext}'. Usa PDF, PPTX, DOCX, MD o TXT.")

    chunks: list[ExtractedChunk] = []

    if ext == ".pdf":
        from pypdf import PdfReader  # type: ignore[import-untyped]

        reader = PdfReader(io.BytesIO(data))
        for idx, page in enumerate(reader.pages, start=1):
            txt = _clean_text(page.extract_text() or "")
            if txt:
                chunks.append(
                    ExtractedChunk(
                        source_file=safe_name,
                        section_title=f"Pagina {idx}",
                        content=txt[:4000],
                    )
                )

    elif ext == ".pptx":
        from pptx import Presentation  # type: ignore[import-untyped]

        prs = Presentation(io.BytesIO(data))
        for idx, slide in enumerate(prs.slides, start=1):
            lines: list[str] = []
            title_text = ""
            if slide.shapes.title and slide.shapes.title.text:
                title_text = slide.shapes.title.text.strip()
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    t = shape.text_frame.text.strip()
                    if t:
                        lines.append(t)
            txt = _clean_text("\n".join(lines))
            if txt and sum(1 for c in txt if c.isalnum()) >= 3:
                clean_slide_title = _sanitize_title(title_text[:60], "")
                sec = f"Slide {idx}: {clean_slide_title}" if clean_slide_title else f"Slide {idx}"
                chunks.append(
                    ExtractedChunk(
                        source_file=safe_name,
                        section_title=sec,
                        content=txt[:4000],
                    )
                )

    elif ext == ".docx":
        from docx import Document  # type: ignore[import-untyped]

        doc = Document(io.BytesIO(data))
        current_title = "Seccion 1"
        current_lines: list[str] = []
        sec_idx = 1
        for para in doc.paragraphs:
            t = para.text.strip()
            if not t or _SEPARATOR_LINE_RE.match(t):
                continue
            style_name = (para.style.name if para.style else "").lower()
            if "heading" in style_name or "titulo" in style_name:
                if current_lines:
                    body_txt = _clean_text("\n".join(current_lines))[:4000]
                    if sum(1 for c in body_txt if c.isalnum()) >= 3:
                        chunks.append(
                            ExtractedChunk(
                                source_file=safe_name,
                                section_title=current_title,
                                content=body_txt,
                            )
                        )
                    current_lines = []
                sec_idx += 1
                current_title = _sanitize_title(t[:80], f"Seccion {sec_idx}")
            else:
                current_lines.append(t)
                if sum(len(x) for x in current_lines) >= 2500:
                    body_txt = _clean_text("\n".join(current_lines))[:4000]
                    if sum(1 for c in body_txt if c.isalnum()) >= 3:
                        chunks.append(
                            ExtractedChunk(
                                source_file=safe_name,
                                section_title=current_title,
                                content=body_txt,
                            )
                        )
                    current_lines = []
                    sec_idx += 1
                    current_title = f"Seccion {sec_idx}"
        if current_lines:
            body_txt = _clean_text("\n".join(current_lines))[:4000]
            if sum(1 for c in body_txt if c.isalnum()) >= 3:
                chunks.append(
                    ExtractedChunk(
                        source_file=safe_name,
                        section_title=current_title,
                        content=body_txt,
                    )
                )

    else:
        # .md o .txt
        raw_text = data.decode("utf-8", errors="replace")
        raw_text = _SEPARATOR_LINE_RE.sub("", raw_text)
        parts = re.split(r"(?m)^(?=#{1,3}\s+)", raw_text)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) <= 1:
            # Dividir por bloques de parrafos
            paras = [p.strip() for p in re.split(r"\n{2,}", raw_text) if p.strip() and _is_valid_title(p)]
            buf: list[str] = []
            sec_idx = 1
            for p in paras:
                buf.append(p)
                if sum(len(x) for x in buf) >= 1200:
                    body_txt = _clean_text("\n\n".join(buf))[:4000]
                    if sum(1 for c in body_txt if c.isalnum()) >= 3:
                        chunks.append(
                            ExtractedChunk(
                                source_file=safe_name,
                                section_title=f"Seccion {sec_idx}",
                                content=body_txt,
                            )
                        )
                    buf = []
                    sec_idx += 1
            if buf:
                body_txt = _clean_text("\n\n".join(buf))[:4000]
                if sum(1 for c in body_txt if c.isalnum()) >= 3:
                    chunks.append(
                        ExtractedChunk(
                            source_file=safe_name,
                            section_title=f"Seccion {sec_idx}",
                            content=body_txt,
                        )
                    )
        else:
            for idx, part in enumerate(parts, start=1):
                first_line, _, rest = part.partition("\n")
                raw_heading = re.sub(r"^#{1,3}\s*", "", first_line).strip()[:80]
                body = _clean_text(rest if rest.strip() else first_line)
                if sum(1 for c in body if c.isalnum()) < 3:
                    continue
                if not _is_valid_title(raw_heading):
                    first_body_line = next((ln.strip() for ln in body.splitlines() if _is_valid_title(ln)), "")
                    heading = _sanitize_title(first_body_line[:65], f"Seccion {idx}")
                else:
                    heading = _sanitize_title(raw_heading, f"Seccion {idx}")
                chunks.append(
                    ExtractedChunk(
                        source_file=safe_name,
                        section_title=heading,
                        content=body[:4000],
                    )
                )

    if not chunks:
        raise ValueError(f"El archivo '{safe_name}' no contiene texto extraible.")
    return chunks


def index_chunks_in_fts(conn: sqlite3.Connection, course_id: str, chunks: list[ExtractedChunk]) -> int:
    """Reemplaza e indexa los chunks del ramo en local_chunks_fts."""
    _, keys = _resolve_fts_course_keys(conn, course_id)
    placeholders = ",".join("?" for _ in keys)
    conn.execute(f"DELETE FROM local_chunks_fts WHERE course_id IN ({placeholders});", tuple(keys))
    for ch in chunks:
        conn.execute(
            """
            INSERT INTO local_chunks_fts (course_id, source_file, section_title, content)
            VALUES (?, ?, ?, ?);
            """,
            (course_id, ch.source_file, ch.section_title, ch.content),
        )
    conn.commit()
    return len(chunks)


def append_chunks_in_fts(conn: sqlite3.Connection, course_id: str, chunks: list[ExtractedChunk]) -> int:
    """Agrega chunks nuevos a local_chunks_fts conservando intactos los archivos previos (reemplaza solo si coincide filename)."""
    _, keys = _resolve_fts_course_keys(conn, course_id)
    key_placeholders = ",".join("?" for _ in keys)
    uploaded_files = sorted({ch.source_file for ch in chunks})
    if uploaded_files:
        file_placeholders = ",".join("?" for _ in uploaded_files)
        conn.execute(
            f"DELETE FROM local_chunks_fts WHERE course_id IN ({key_placeholders}) AND source_file IN ({file_placeholders});",
            (*keys, *uploaded_files),
        )
    for ch in chunks:
        conn.execute(
            """
            INSERT INTO local_chunks_fts (course_id, source_file, section_title, content)
            VALUES (?, ?, ?, ?);
            """,
            (course_id, ch.source_file, ch.section_title, ch.content),
        )
    conn.commit()
    row = conn.execute(
        f"SELECT COUNT(*) AS total FROM local_chunks_fts WHERE course_id IN ({key_placeholders});",
        tuple(keys),
    ).fetchone()
    return int(row["total"]) if row else len(chunks)


def _strip_bullet_lists(story: str) -> str:
    """Convierte cualquier linea con viñetas en prosa fluida preservando bloques de codigo cercados."""
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
    prose = re.sub(r"\n{3,}", "\n\n", prose).strip()
    return prose


def _build_fallback_story(
    *,
    explanation_style: str,
    title: str,
    course_title: str,
    world_metaphor: str,
    text_snippet: str,
    key_phrases: list[str],
    engine_type: str = "concept_tree",
    default_language: str = "text",
) -> str:
    code_section = (
        f"\n\n{_fallback_story_code_block(title, default_language)}\n\n"
        if engine_type == "code_lab"
        else "\n\n"
    )
    if explanation_style == "direct":
        return _strip_bullet_lists(
            f"**{title}** en {course_title} aborda directamente los **fundamentos técnicos** extraídos de tus apuntes: "
            f"{text_snippet[:480]}.\n\n"
            f"El **mecanismo principal** establece que {key_phrases[0]}. Además, para garantizar una operación "
            f"correcta del sistema se requiere que {key_phrases[1]}."
            f"{code_section}"
            f"Al evaluar **{title}** en {course_title}, verifica qué **invariante** protege este componente y qué "
            f"consecuencia técnica ocurre si esa condición deja de cumplirse."
        )
    if explanation_style == "structured":
        return _strip_bullet_lists(
            f"Concepto central: **{title}** dentro de {course_title} estructura los **principios técnicos** descritos en tus apuntes: "
            f"{text_snippet[:480]}.\n\n"
            f"Causa y efecto: La **relación causal** principal determina que {key_phrases[0]}. Como consecuencia directa, "
            f"{key_phrases[1]} cuando el sistema opera bajo **condiciones reales**."
            f"{code_section}"
            f"Ejemplo concreto: En una aplicación práctica o evaluación de {course_title}, comprobar las propiedades "
            f"de **{title}** permite diagnosticar fallos y justificar la solución técnica paso a paso."
        )
    return _strip_bullet_lists(
        f"Situémonos en {world_metaphor} para entender por qué **{title}** es una pieza fundamental dentro de "
        f"{course_title}. Cuando observamos el sistema en **operación real**, lo primero que salta a la vista es cómo "
        f"se encadenan las decisiones técnicas a partir de tus apuntes: {text_snippet[:480]}.\n\n"
        f"Si lo llevas a un escenario concreto dentro de {world_metaphor}, no basta con repetir definiciones "
        f"de memoria. Lo decisivo es seguir la relación de **causa y efecto** paso a paso: {key_phrases[0]}. "
        f"Además, ten siempre presente que {key_phrases[1]}, porque esa conexión explica cómo interactúan "
        f"los componentes cuando la carga o la complejidad aumentan."
        f"{code_section}"
        f"Por eso, al enfrentarte a un caso práctico o examen de {course_title} dentro de {world_metaphor}, "
        f"pregúntate primero qué **invariante** protege **{title}** y qué ocurriría si esa pieza fallara; así podrás "
        f"diagnosticar y justificar tu solución con criterio propio."
    )


def _build_fallback_question(
    *,
    question_style: str,
    title: str,
    course_title: str,
    world_metaphor: str,
) -> str:
    if question_style == "scenario":
        return (
            f"En un caso aplicado dentro de {world_metaphor}, ¿como funciona {title} y como diagnosticarias "
            f"un problema real en {course_title}?"
        )
    return f"Explica con precision tecnica como funciona {title} y que problema concreto resuelve en {course_title}."


def _fallback_nodes_from_chunks(
    *,
    course_title: str,
    world_metaphor: str,
    chunks: list[ExtractedChunk],
    explanation_style: str = "narrative",
    question_style: str = "direct",
    engine_type: str = "concept_tree",
    default_language: str = "text",
) -> list[dict[str, Any]]:
    """Construye de 6 a 8 nodos reales (theory + practice) a partir de los apuntes cuando no hay IA externa."""
    # Agrupar o expandir chunks para tener al menos 6 segmentos tematicos
    segments: list[tuple[str, str]] = []
    for ch in chunks:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", ch.content) if len(s.strip()) > 25]
        if not sentences:
            sentences = [ch.content[:300]]
        segments.append((ch.section_title, " ".join(sentences[:6])))

    while len(segments) < 6:
        idx = len(segments) + 1
        base_title, base_text = segments[(idx - 1) % max(1, len(segments))]
        segments.append((f"{base_title} · Profundizacion {idx}", base_text))

    selected = segments[:8]
    theory_count = max(4, len(selected) - 2)
    nodes: list[dict[str, Any]] = []

    for i, (sec_title, text_snippet) in enumerate(selected, start=1):
        is_theory = i <= theory_count
        branch = "theory" if is_theory else "practice"
        nid = f"N{i}"
        if is_theory:
            # Organizar teoria en 3 columnas paralelas (2 livelli por columna) en vez de 1 torre vertical
            col_idx = ((i - 1) // 2) + 1
            if i % 2 == 1:
                parents: list[str] = []
            else:
                parents = [f"N{i - 1}"]
            block = f"Bloque {col_idx} · Fundamentos Teoricos"
        else:
            parents = ["N1"] if i == theory_count + 1 else [f"N{i - 1}"]
            block = "Bloque Practico · Examenes y Casos"
        raw_sec = re.sub(r"^(Seccion|Pagina|Slide)\s+\d+[:\s]*", "", sec_title).strip()
        clean_title = _sanitize_title(raw_sec, f"Concepto {i}")
        title = f"{clean_title[:70]}" if is_theory else f"Taller Practico: {clean_title[:58]}"

        key_phrases = [
            s.strip().rstrip(".")
            for s in re.split(r"[.;]\s+|\n+", text_snippet)
            if len(s.strip()) >= 20 and _is_valid_title(s)
        ][:3]
        while len(key_phrases) < 2:
            key_phrases.append(f"Explica el rol de {title} dentro de {course_title}")

        story_script = _build_fallback_story(
            explanation_style=explanation_style,
            title=title,
            course_title=course_title,
            world_metaphor=world_metaphor,
            text_snippet=text_snippet,
            key_phrases=key_phrases,
            engine_type=engine_type,
            default_language=default_language,
        )
        q_text = _build_fallback_question(
            question_style=question_style,
            title=title,
            course_title=course_title,
            world_metaphor=world_metaphor,
        )

        if engine_type == "code_lab":
            eval_prompts = _build_fallback_code_lab_prompts(
                branch=branch,
                title=title,
                course_title=course_title,
                world_metaphor=world_metaphor,
                question_style=question_style,
                key_phrases=key_phrases,
                default_language=default_language,
                node_index=i,
            )
        else:
            eval_prompts = [
                {
                    "id": "q1",
                    "question": q_text,
                    "rubric_points": [p[:160] for p in key_phrases[:3]],
                    "challenge_type": "concept",
                    "language": "text",
                    "starter_code": None,
                }
            ]

        nodes.append(
            {
                "id": nid,
                "parent_ids": parents,
                "branch": branch,
                "block": block,
                "title": title,
                "summary": f"Comprension aplicada de {title} en el contexto de {course_title}.",
                "story_script": story_script,
                "eval_prompts": eval_prompts,
                "storyboard_ref": None,
            }
        )

    return nodes


def _sample_chunks_balanced(
    chunks: list[ExtractedChunk],
    *,
    max_chunks: int = 36,
    max_chars: int = 26000,
) -> str:
    """Muestrea equitativamente todos los archivos subidos (round-robin por archivo) sin cortar los ultimos."""
    by_file: dict[str, list[ExtractedChunk]] = {}
    for ch in chunks:
        by_file.setdefault(ch.source_file, []).append(ch)

    file_queues: list[list[ExtractedChunk]] = []
    for file_chunks in by_file.values():
        if len(file_chunks) <= 8:
            file_queues.append(list(file_chunks))
        else:
            # Distribuye indices a lo largo de todo el archivo (inicio, medio y fin)
            step = max(1, len(file_chunks) // 8)
            sampled = [file_chunks[i] for i in range(0, len(file_chunks), step)][:8]
            file_queues.append(sampled)

    selected: list[ExtractedChunk] = []
    while file_queues and len(selected) < max_chunks:
        next_queues: list[list[ExtractedChunk]] = []
        for q in file_queues:
            if q and len(selected) < max_chunks:
                selected.append(q.pop(0))
            if q:
                next_queues.append(q)
        file_queues = next_queues

    per_chunk_limit = max(450, max_chars // max(1, len(selected)))
    items = [
        f"[{c.source_file} - {c.section_title}]: {c.content[:per_chunk_limit]}"
        for c in selected
    ]
    return "\n\n".join(items)[:max_chars]


def _code_lab_architect_rules(default_language: str) -> str:
    lang = default_language if default_language in ("java", "sql", "python", "c") else "java"
    return (
        f"\nMODO ESPECIAL `code_lab` ACTIVO (Lenguaje dominante: `{lang}`):\n"
        f"- BLOQUE DE CODIGO EN `story_script`: En cada nodo cuando `engine_type == \"code_lab\"`, incluye en `story_script` "
        f"1 ejemplo de codigo real corto y limpio (10 a 22 lineas) en un bloque Markdown cercado (```{lang} ... ```) "
        f"— o hasta 2 micro-fragmentos de 4 a 8 lineas si contrastan un error vs. su correccion — que enseñe explicitamente "
        f"la sintaxis, anotaciones y mecanismos que se evaluaran en ese nodo.\n"
        f"- En cada nodo `branch: \"theory\"`: genera 3 `eval_prompts` combinando al menos 1 pregunta conceptual "
        f"(`\"challenge_type\": \"concept\"`, `\"starter_code\": null`) + 1 a 2 desafios de codigo reales "
        f"(`\"challenge_type\": \"trace\" | \"debug\" | \"implement\"`, `\"language\": \"{lang}\"`).\n"
        f"- En cada nodo `branch: \"practice\"` (Examenes / Laboratorios): genera desafios practicos de codigo reales "
        f"(`\"challenge_type\": \"debug\"` e `\"implement\"`, `\"language\": \"{lang}\"`) estilo certamen universitario.\n"
        f"- REGLA ESTRICTA DE `starter_code` Y `question`:\n"
        f"  * `debug` y `trace`: SI incluyen el codigo completo necesario en `starter_code` (con el bug concreto a "
        f"corregir o el fragmento completo a trazar paso a paso), SIEMPRE formateado en multiples lineas con `\\n` "
        f"e indentacion de 2 o 4 espacios (PROHIBIDO entregar el codigo en una sola linea).\n"
        f"  * PROHIBIDO DUPLICAR CODIGO EN `question`: Cuando exista `starter_code` (`debug` o `trace`), `question` "
        f"NUNCA debe repetir ni incluir el codigo (solo debe indicar la tarea: que bug corregir o que trazar).\n"
        f"  * `implement` en nodos basicos/intermedios (clases, constructores, arreglos, herencia basica, excepciones basicas): "
        f"`starter_code` DEBE ir vacio (`\"\"`) o solo un comentario de 1 linea (`// Implementa tu solución en Java aquí`) "
        f"— PROHIBIDO regalar el esqueleto resuelto de la clase/metodos con `// TODO`.\n"
        f"  * `implement` en nodos avanzados (patrones de diseno, Swing/MVC, integraciones): solo puede incluir "
        f"clases/interfaces auxiliares de contexto que el estudiante usara, NUNCA el esqueleto ya resuelto del metodo o "
        f"clase que debe construir.\n"
    )


def _generate_nodes_with_ai(
    *,
    course_code: str,
    course_title: str,
    world_metaphor: str,
    chunks: list[ExtractedChunk],
    preferred_provider: str = "auto",
    explanation_style: str = "narrative",
    question_style: str = "direct",
    engine_type: str = "concept_tree",
    default_language: str = "text",
) -> tuple[list[dict[str, Any]], str]:
    """Usa ai_router para sintetizar un arbol profundo de 8..16 nodos (copa theory + raices practice/examenes)."""
    digest_text = _sample_chunks_balanced(chunks)
    files_list = sorted({c.source_file for c in chunks})
    exp_rule = explanation_style_instruction(explanation_style, world_metaphor)
    q_rule = question_style_instruction(question_style, world_metaphor)
    code_lab_extra = _code_lab_architect_rules(default_language) if engine_type == "code_lab" else ""
    lang_hint = default_language if engine_type == "code_lab" else "text"

    system_prompt = (
        "Eres el Arquitecto Pedagogico de Brotal. Convierte apuntes universitarios en un Arbol de Habilidades "
        "JSON profundo y exigente con ENTRE 8 Y 16 NODOS (si el material es muy corto, minimo 6):\n"
        "- COPA SUPERIOR (`branch: \"theory\"`): entre 6 y 11 nodos conceptuales organizados en **3 a 4 ramas/bloques "
        "paralelos** (PROHIBIDO formar una sola torre vertical de 1 columna). El primer nodo de cada bloque principal "
        "DEBE llevar `parent_ids: []` para salir directo desde el nucleo central, y cada columna/bloque crece solo "
        "2 a 3 niveles hacia arriba.\n"
        "- RAICES INFERIORES (`branch: \"practice\"`): entre 3 y 5 nodos explicitos de EXAMENES, CONTROLES, LABS o CASOS REALES "
        "(ej. 'Examen Parcial 1 · ...', 'Caso Practico / Debugging · ...', 'Simulacro Examen Final'), "
        "conectados en `parent_ids` a los nodos 'theory' que ponen a prueba.\n"
        "REGLAS OBLIGATORIAS:\n"
        f"1. `story_script` DEBE seguir esta preferencia del estudiante: {exp_rule}\n"
        "2. DESTACADOS VISUALES EN `story_script`: Marca entre 3 y 6 conceptos, reglas o palabras clave fundamentales "
        "por historia con `**negrita**` (ej. `**polimorfismo dinamico**`, `**@Override**`, `**pasa por valor**`).\n"
        "3. CONTRATO ESTRICTO DE COBERTURA EXPLICACION <-> PREGUNTAS: El `story_script` DEBE explicar de forma explicita "
        "y suficiente TODOS los conceptos, sintaxis, anotaciones y `rubric_points` que se evaluaran en `eval_prompts` "
        "de ese nodo (ej. si una pregunta exige `@Override` o `super()`, `story_script` debe enseñarlo explicitamente "
        "con ejemplo). PROHIBIDO exigir en `eval_prompts` sintaxis, anotaciones o conceptos que no aparezcan en `story_script`.\n"
        "4. Ningun titulo (`title`) puede ser una linea separadora (`---`, `===`, `***`) ni tener menos de 3 caracteres alfanumericos.\n"
        "5. Los nodos iniciales de los 3 a 4 bloques 'theory' llevan `parent_ids: []`. Los siguientes niveles de cada bloque "
        "conectan `parent_ids` al nodo inferior de su bloque formando 3 a 4 columnas paralelas de 2 a 3 niveles.\n"
        f"6. Cada nodo DEBE incluir `eval_prompts` con 3 a 4 preguntas a ciegas siguiendo este estilo: {q_rule} "
        "Cada pregunta lleva 2 a 3 `rubric_points` concretos y verificables.\n"
        "7. Cubre TODOS los archivos entregados, no solo el primero.\n"
        f"{code_lab_extra}"
        "Responde UNICAMENTE JSON valido con la clave `nodes`:\n"
        "{\n"
        '  "world_metaphor": "...",\n'
        '  "nodes": [\n'
        "    {\n"
        '      "id": "T1",\n'
        '      "parent_ids": [],\n'
        '      "branch": "theory",\n'
        '      "block": "Bloque 1 · Fundamentos",\n'
        '      "title": "...",\n'
        '      "summary": "...",\n'
        '      "story_script": "Parrafo 1...\\n\\nParrafo 2...",\n'
        '      "eval_prompts": [\n'
        f'        {{"id": "q1", "question": "...", "rubric_points": ["...", "..."], "challenge_type": "concept", "language": "{lang_hint}", "starter_code": null}},\n'
        f'        {{"id": "q2", "question": "...", "rubric_points": ["...", "..."], "challenge_type": "debug", "language": "{lang_hint}", "starter_code": "..."}},\n'
        f'        {{"id": "q3", "question": "...", "rubric_points": ["...", "..."], "challenge_type": "implement", "language": "{lang_hint}", "starter_code": "// Implementa tu solución en Java aquí"}}\n'
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    user_prompt = (
        f"Codigo: {course_code}\n"
        f"Ramo: {course_title}\n"
        f"Motor de estudio: {engine_type} (lenguaje: {lang_hint})\n"
        f"Estilo de explicacion: {explanation_style}\n"
        f"Estilo de preguntas: {question_style}\n"
        f"Metafora del mundo sugerida: {world_metaphor}\n"
        f"Archivos subidos ({len(files_list)}): {', '.join(files_list)}\n\n"
        f"Apuntes muestreados de todos los archivos:\n{digest_text}"
    )

    try:
        comp = ai_router.complete_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            preferred_provider=preferred_provider,
            json_mode=True,
            temperature=0.35,
            max_tokens=8192,
            timeout=90.0,
        )
        parsed = extract_json_object(comp.text)
        raw_nodes = parsed.get("nodes")
        if not isinstance(raw_nodes, list) or len(raw_nodes) < 6:
            raise ValueError("El LLM devolvio menos de 6 nodos")

        normalized_nodes: list[dict[str, Any]] = []
        capped_nodes = raw_nodes[:16]
        valid_ids = {str(n.get("id") or f"N{idx+1}") for idx, n in enumerate(capped_nodes)}

        for idx, n in enumerate(capped_nodes):
            nid = str(n.get("id") or f"N{idx+1}")
            raw_parents = [str(p) for p in (n.get("parent_ids") or []) if str(p) in valid_ids and str(p) != nid]
            branch = "practice" if str(n.get("branch")).lower() == "practice" else "theory"
            if idx == 0:
                raw_parents = []
                branch = "theory"
            elif idx == len(capped_nodes) - 1 and not any(x.get("branch") == "practice" for x in normalized_nodes):
                branch = "practice"

            safe_title = _sanitize_title(str(n.get("title") or ""), f"Nodo {idx+1} · {course_title}")
            safe_block = _sanitize_title(
                str(n.get("block") or ""),
                "Bloque Practico" if branch == "practice" else "Bloque Conceptual",
            )

            raw_prompts = n.get("eval_prompts") or []
            clean_prompts = [
                _normalize_prompt_item(
                    p,
                    p_idx=p_idx,
                    node_title=safe_title,
                    nid=nid,
                    engine_type=engine_type,
                    default_language=default_language,
                )
                for p_idx, p in enumerate(raw_prompts[:5], start=1)
                if isinstance(p, dict)
            ]

            if engine_type == "code_lab":
                has_code_challenge = any(
                    cp.get("challenge_type") in ("trace", "debug", "implement")
                    for cp in clean_prompts
                )
                if not has_code_challenge:
                    fallback_code_prompts = _build_fallback_code_lab_prompts(
                        branch=branch,
                        title=safe_title,
                        course_title=course_title,
                        world_metaphor=world_metaphor,
                        question_style=question_style,
                        key_phrases=[
                            f"Define y aplica correctamente {safe_title}",
                            f"Maneja casos borde y sintaxis de {default_language.upper()}",
                        ],
                        default_language=default_language,
                        node_index=idx + 1,
                    )
                    if clean_prompts and branch == "theory":
                        clean_prompts = [clean_prompts[0], *fallback_code_prompts[1:]]
                    else:
                        clean_prompts = fallback_code_prompts

            if not clean_prompts:
                clean_prompts = [
                    {
                        "id": "q1",
                        "question": f"¿Como explicarias {safe_title} y su aplicacion practica?",
                        "rubric_points": [
                            f"Define la idea principal de {safe_title}",
                            "Conecta el concepto con un caso practico del ramo",
                        ],
                        "challenge_type": "concept",
                        "language": lang_hint,
                        "starter_code": None,
                    }
                ]

            normalized_nodes.append(
                {
                    "id": nid,
                    "parent_ids": raw_parents,
                    "branch": branch,
                    "block": safe_block,
                    "title": safe_title,
                    "summary": str(n.get("summary") or f"Conceptos clave de {course_title}"),
                    "story_script": _strip_bullet_lists(str(n.get("story_script") or "")),
                    "eval_prompts": clean_prompts,
                    "storyboard_ref": None,
                }
            )

        return (normalized_nodes, comp.provider)
    except (AiProviderError, ValueError, KeyError, json.JSONDecodeError):
        fallback = _fallback_nodes_from_chunks(
            course_title=course_title,
            world_metaphor=world_metaphor,
            chunks=chunks,
            explanation_style=explanation_style,
            question_style=question_style,
            engine_type=engine_type,
            default_language=default_language,
        )
        return (fallback, "local_fallback")


_generate_tree_with_ai = _generate_nodes_with_ai


def _next_unique_node_id(prefix: str, start_idx: int, used_ids: set[str]) -> str:
    idx = start_idx
    while f"{prefix}{idx}" in used_ids:
        idx += 1
    nid = f"{prefix}{idx}"
    used_ids.add(nid)
    return nid


def _fallback_append_nodes_from_chunks(
    *,
    course_title: str,
    world_metaphor: str,
    chunks: list[ExtractedChunk],
    existing_nodes: list[dict[str, Any]],
    explanation_style: str = "narrative",
    question_style: str = "direct",
    engine_type: str = "concept_tree",
    default_language: str = "text",
) -> list[dict[str, Any]]:
    """Construye de 2 a 4 nodos nuevos conectados al arbol existente cuando no hay IA externa."""
    existing_ids = {str(n["id"]) for n in existing_nodes}
    used_ids = set(existing_ids)

    theory_anchors = [str(n["id"]) for n in existing_nodes if n.get("branch") == "theory"]
    anchor_id = theory_anchors[-1] if theory_anchors else str(existing_nodes[-1]["id"])

    segments: list[tuple[str, str]] = []
    for ch in chunks:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", ch.content) if len(s.strip()) > 25]
        if not sentences:
            sentences = [ch.content[:300]]
        segments.append((ch.section_title, " ".join(sentences[:6])))

    while len(segments) < 2:
        idx = len(segments) + 1
        base_title, base_text = segments[(idx - 1) % max(1, len(segments))]
        segments.append((f"{base_title} · Aplicacion {idx}", base_text))

    selected = segments[:4]
    theory_count = max(1, len(selected) - 1)
    nodes: list[dict[str, Any]] = []
    prev_theory_id = anchor_id

    for i, (sec_title, text_snippet) in enumerate(selected, start=1):
        is_theory = i <= theory_count
        branch = "theory" if is_theory else "practice"
        nid = _next_unique_node_id("A", i, used_ids)
        if is_theory:
            parents = [prev_theory_id]
            prev_theory_id = nid
        else:
            parents = [prev_theory_id]

        block = "Bloque Incremental · Teoria" if is_theory else "Bloque Incremental · Practica"
        raw_sec = re.sub(r"^(Seccion|Pagina|Slide)\s+\d+[:\s]*", "", sec_title).strip()
        clean_title = _sanitize_title(raw_sec, f"Tema Incremental {i}")
        title = f"{clean_title[:70]}" if is_theory else f"Taller Practico: {clean_title[:58]}"

        key_phrases = [
            s.strip().rstrip(".")
            for s in re.split(r"[.;]\s+|\n+", text_snippet)
            if len(s.strip()) >= 20 and _is_valid_title(s)
        ][:3]
        while len(key_phrases) < 2:
            key_phrases.append(f"Explica el rol de {title} dentro de {course_title}")

        story_script = _build_fallback_story(
            explanation_style=explanation_style,
            title=title,
            course_title=course_title,
            world_metaphor=world_metaphor,
            text_snippet=text_snippet,
            key_phrases=key_phrases,
            engine_type=engine_type,
            default_language=default_language,
        )
        q_text = _build_fallback_question(
            question_style=question_style,
            title=title,
            course_title=course_title,
            world_metaphor=world_metaphor,
        )

        if engine_type == "code_lab":
            eval_prompts = _build_fallback_code_lab_prompts(
                branch=branch,
                title=title,
                course_title=course_title,
                world_metaphor=world_metaphor,
                question_style=question_style,
                key_phrases=key_phrases,
                default_language=default_language,
                node_index=i,
            )
        else:
            eval_prompts = [
                {
                    "id": "q1",
                    "question": q_text,
                    "rubric_points": [p[:160] for p in key_phrases[:3]],
                    "challenge_type": "concept",
                    "language": "text",
                    "starter_code": None,
                }
            ]

        nodes.append(
            {
                "id": nid,
                "parent_ids": parents,
                "branch": branch,
                "block": block,
                "title": title,
                "summary": f"Extension incremental sobre {title} en {course_title}.",
                "story_script": story_script,
                "eval_prompts": eval_prompts,
                "storyboard_ref": None,
            }
        )

    return nodes


def _generate_append_nodes_with_ai(
    *,
    course_code: str,
    course_title: str,
    world_metaphor: str,
    chunks: list[ExtractedChunk],
    existing_nodes: list[dict[str, Any]],
    preferred_provider: str = "auto",
    explanation_style: str = "narrative",
    question_style: str = "direct",
    engine_type: str = "concept_tree",
    default_language: str = "text",
) -> tuple[list[dict[str, Any]], str]:
    """Genera entre 2 y 6 nodos nuevos conectados al arbol existente sin tocar los nodos previos."""
    digest_text = _sample_chunks_balanced(chunks)
    files_list = sorted({c.source_file for c in chunks})
    existing_ids = {str(n["id"]) for n in existing_nodes}
    theory_anchors = [str(n["id"]) for n in existing_nodes if n.get("branch") == "theory"]
    anchor_id = theory_anchors[-1] if theory_anchors else str(existing_nodes[-1]["id"])
    exp_rule = explanation_style_instruction(explanation_style, world_metaphor)
    q_rule = question_style_instruction(question_style, world_metaphor)
    code_lab_extra = _code_lab_architect_rules(default_language) if engine_type == "code_lab" else ""

    system_prompt = (
        "Eres el Arquitecto Pedagogico de Brotal en MODO INCREMENTAL (`append`).\n"
        "El estudiante ya tiene un Arbol de Habilidades activo con progreso guardado y acaba de subir material nuevo.\n"
        "Debes generar UNICAMENTE LOS NODOS NUEVOS (ENTRE 2 Y 6 NODOS, `theory` y/o `practice`) que cubren los archivos nuevos:\n"
        "REGLAS OBLIGATORIAS:\n"
        "1. NO repitas ni devuelvas los nodos existentes; devuelve SOLO los 2 a 6 nodos nuevos.\n"
        "2. Cada nodo nuevo DEBE tener un `id` unico que NO colisione con ningun `id` existente (ej. 'A1', 'A2', 'P_NEW1').\n"
        "3. `parent_ids` de cada nodo nuevo DEBE conectarse al menos a un nodo existente del arbol (o a otro nodo nuevo recien creado) "
        "para que quede integrado en el DAG.\n"
        f"4. `story_script` DEBE seguir esta preferencia: {exp_rule}\n"
        "5. DESTACADOS VISUALES EN `story_script`: Marca entre 3 y 6 conceptos, reglas o palabras clave por historia con `**negrita**`.\n"
        "6. CONTRATO ESTRICTO DE COBERTURA EXPLICACION <-> PREGUNTAS: El `story_script` DEBE explicar explicitamente todos los "
        "conceptos, sintaxis, anotaciones y `rubric_points` evaluados en `eval_prompts` de ese nodo. PROHIBIDO evaluar en "
        "`eval_prompts` sintaxis o conceptos que no aparezcan en `story_script`.\n"
        f"7. Cada nodo nuevo DEBE incluir `eval_prompts` con 2 a 4 preguntas a ciegas ({q_rule}) y 2 a 3 `rubric_points` verificables.\n"
        f"{code_lab_extra}"
        "Responde UNICAMENTE JSON valido con la clave `nodes`."
    )
    user_prompt = (
        f"Codigo: {course_code}\n"
        f"Ramo: {course_title}\n"
        f"Motor de estudio: {engine_type} (lenguaje: {default_language})\n"
        f"Metafora del mundo: {world_metaphor}\n"
        f"Nodos existentes en el arbol (NO los repitas, usalos para conectar `parent_ids`):\n"
        f"{json.dumps(existing_nodes, ensure_ascii=False)}\n\n"
        f"Archivos nuevos subidos ({len(files_list)}): {', '.join(files_list)}\n\n"
        f"Apuntes de los archivos nuevos:\n{digest_text}"
    )

    try:
        comp = ai_router.complete_chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            preferred_provider=preferred_provider,
            json_mode=True,
            temperature=0.35,
            max_tokens=6144,
            timeout=90.0,
        )
        parsed = extract_json_object(comp.text)
        raw_nodes = parsed.get("nodes")
        if not isinstance(raw_nodes, list) or len(raw_nodes) < 2:
            raise ValueError("El LLM devolvio menos de 2 nodos incrementales")

        capped_nodes = raw_nodes[:6]
        used_ids = set(existing_ids)
        assigned_ids: list[str] = []
        raw_to_assigned: dict[str, str] = {}

        for idx, n in enumerate(capped_nodes, start=1):
            candidate = str(n.get("id") or "").strip()
            if not candidate or candidate in used_ids:
                nid = _next_unique_node_id("A", idx, used_ids)
            else:
                nid = candidate
                used_ids.add(nid)
            assigned_ids.append(nid)
            if candidate:
                raw_to_assigned[candidate] = nid

        valid_parent_universe = existing_ids | set(assigned_ids)
        normalized_nodes: list[dict[str, Any]] = []

        for idx, (n, nid) in enumerate(zip(capped_nodes, assigned_ids, strict=True)):
            mapped_parents: list[str] = []
            for p in n.get("parent_ids") or []:
                p_str = str(p).strip()
                resolved_p = raw_to_assigned.get(p_str, p_str)
                if resolved_p in valid_parent_universe and resolved_p != nid and resolved_p not in mapped_parents:
                    mapped_parents.append(resolved_p)

            if not mapped_parents:
                mapped_parents = [anchor_id if idx == 0 else assigned_ids[idx - 1]]

            branch = "practice" if str(n.get("branch")).lower() == "practice" else "theory"
            safe_title = _sanitize_title(str(n.get("title") or ""), f"Tema Nuevo {idx + 1} · {course_title}")
            safe_block = _sanitize_title(
                str(n.get("block") or ""),
                "Bloque Practico Incremental" if branch == "practice" else "Bloque Conceptual Incremental",
            )

            raw_prompts = n.get("eval_prompts") or []
            clean_prompts = [
                _normalize_prompt_item(
                    p,
                    p_idx=p_idx,
                    node_title=safe_title,
                    nid=nid,
                    engine_type=engine_type,
                    default_language=default_language,
                )
                for p_idx, p in enumerate(raw_prompts[:5], start=1)
                if isinstance(p, dict)
            ]
            if not clean_prompts:
                clean_prompts = [
                    {
                        "id": "q1",
                        "question": f"¿Como explicarias {safe_title} y su conexion con el ramo?",
                        "rubric_points": [
                            f"Define la idea principal de {safe_title}",
                            "Conecta el concepto con un caso practico del ramo",
                        ],
                        "challenge_type": "concept",
                        "language": default_language if engine_type == "code_lab" else "text",
                        "starter_code": None,
                    }
                ]

            normalized_nodes.append(
                {
                    "id": nid,
                    "parent_ids": mapped_parents,
                    "branch": branch,
                    "block": safe_block,
                    "title": safe_title,
                    "summary": str(n.get("summary") or f"Conceptos incrementales de {course_title}"),
                    "story_script": _strip_bullet_lists(str(n.get("story_script") or "")),
                    "eval_prompts": clean_prompts,
                    "storyboard_ref": None,
                }
            )

        return (normalized_nodes, comp.provider)
    except (AiProviderError, ValueError, KeyError, json.JSONDecodeError):
        fallback = _fallback_append_nodes_from_chunks(
            course_title=course_title,
            world_metaphor=world_metaphor,
            chunks=chunks,
            existing_nodes=existing_nodes,
            explanation_style=explanation_style,
            question_style=question_style,
            engine_type=engine_type,
            default_language=default_language,
        )
        return (fallback, "local_fallback")


def ingest_local_files(
    conn: sqlite3.Connection,
    *,
    course_code: str,
    title: str,
    career_id: str | None,
    world_metaphor: str | None,
    files: list[tuple[str, bytes]],
    preferred_provider: str = "auto",
    mode: Literal["append", "replace"] = "replace",
    explanation_style: str = "narrative",
    question_style: str = "direct",
    engine_type: Literal["auto", "concept_tree", "code_lab"] = "auto",
) -> dict[str, Any]:
    """Procesa 1..N archivos locales, indexa en FTS5 y reemplaza o agrega nodos al ramo ('replace' | 'append')."""
    if not files:
        raise ValueError("Debes subir al menos 1 archivo (.pdf, .pptx, .docx, .md o .txt).")

    all_chunks: list[ExtractedChunk] = []
    processed_files: list[dict[str, Any]] = []
    skipped_files: list[dict[str, str]] = []

    for fname, raw_bytes in files:
        try:
            file_chunks = extract_chunks_from_bytes(fname, raw_bytes)
        except ValueError as exc:
            skipped_files.append({"filename": Path(fname).name, "reason": str(exc)})
            continue
        all_chunks.extend(file_chunks)
        processed_files.append(
            {
                "filename": Path(fname).name,
                "sections": len(file_chunks),
                "chars": sum(len(c.content) for c in file_chunks),
            }
        )

    if not all_chunks:
        if len(skipped_files) == 1:
            raise ValueError(skipped_files[0]["reason"])
        names = ", ".join(s["filename"] for s in skipped_files)
        raise ValueError(f"Ninguno de los archivos contiene texto extraible ({names}).")

    clean_code = course_code.strip().upper() or "LOCAL101"
    clean_title = title.strip() or clean_code
    slug = re.sub(r"[^a-z0-9]+", "-", clean_code.lower()).strip("-") or "course"
    course_id = f"local-{slug}"

    detected_engine, detected_lang = detect_engine_type(clean_code, clean_title, all_chunks)
    if engine_type in ("concept_tree", "code_lab"):
        effective_engine: Literal["concept_tree", "code_lab"] = engine_type
        effective_lang = (detected_lang if detected_lang != "text" else "java") if engine_type == "code_lab" else "text"
    else:
        effective_engine = "code_lab" if detected_engine == "code_lab" else "concept_tree"
        effective_lang = detected_lang if effective_engine == "code_lab" else "text"

    existing_row = resolve_course_row(conn, clean_code) or resolve_course_row(conn, course_id)
    existing_node_rows: list[sqlite3.Row] = []
    if existing_row is not None:
        existing_node_rows = conn.execute(
            "SELECT id, title, block_label, branch FROM course_nodes WHERE course_id = ? ORDER BY rowid ASC;",
            (existing_row["id"],),
        ).fetchall()

    if mode == "append" and existing_row is not None and len(existing_node_rows) > 0:
        real_course_id = str(existing_row["id"])
        if engine_type == "auto" and existing_row["engine_type"] == "code_lab":
            effective_engine = "code_lab"
            if effective_lang == "text":
                effective_lang = "java"

        existing_metaphor = ""
        if existing_row["pack_metadata_json"]:
            try:
                meta_dict = json.loads(existing_row["pack_metadata_json"])
                if isinstance(meta_dict, dict):
                    existing_metaphor = str(meta_dict.get("world_metaphor") or "").strip()
            except json.JSONDecodeError:
                existing_metaphor = ""

        metaphor = (world_metaphor or "").strip() or existing_metaphor or f"Laboratorio central de {clean_title}"
        existing_summary = [
            {
                "id": str(r["id"]),
                "title": str(r["title"]),
                "block": str(r["block_label"] or ""),
                "branch": str(r["branch"]),
            }
            for r in existing_node_rows
        ]
        new_nodes, provider_used = _generate_append_nodes_with_ai(
            course_code=clean_code,
            course_title=clean_title,
            world_metaphor=metaphor,
            chunks=all_chunks,
            existing_nodes=existing_summary,
            preferred_provider=preferred_provider,
            explanation_style=explanation_style,
            question_style=question_style,
            engine_type=effective_engine,
            default_language=effective_lang,
        )
        added_count = append_nodes_to_course(conn, real_course_id, new_nodes)
        conn.execute(
            "UPDATE courses SET engine_type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (effective_engine, real_course_id),
        )
        conn.commit()
        total_chunks = append_chunks_in_fts(conn, real_course_id, all_chunks)
        total_nodes_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM course_nodes WHERE course_id = ?;",
            (real_course_id,),
        ).fetchone()
        total_node_count = int(total_nodes_row["cnt"]) if total_nodes_row else (len(existing_node_rows) + added_count)

        return {
            "course_id": real_course_id,
            "course_code": str(existing_row["course_code"] or clean_code),
            "title": str(existing_row["title"] or clean_title),
            "engine_type": effective_engine,
            "detected_language": effective_lang,
            "status": "active",
            "mode": "append",
            "added_nodes": added_count,
            "node_count": total_node_count,
            "chunks_indexed": total_chunks,
            "processed_files": processed_files,
            "skipped_files": skipped_files,
            "provider": provider_used,
            "world_metaphor": metaphor,
        }

    metaphor = (world_metaphor or "").strip() or f"Laboratorio central de {clean_title}"

    nodes, provider_used = _generate_nodes_with_ai(
        course_code=clean_code,
        course_title=clean_title,
        world_metaphor=metaphor,
        chunks=all_chunks,
        preferred_provider=preferred_provider,
        explanation_style=explanation_style,
        question_style=question_style,
        engine_type=effective_engine,
        default_language=effective_lang,
    )

    year_now = datetime.now(UTC).year
    pack_obj = CoursePack(
        schema_version="1.0",
        id=course_id,
        course_code=clean_code,
        title=clean_title,
        language="es",
        engine_type=effective_engine,
        metadata=PackMetadata(
            university_id="local",
            career_ids=[career_id] if career_id else [],
            created_year=year_now,
            updated_year=year_now,
            version="1.0.0",
            authors=["Local BYOF"],
            license="CC-BY-SA-4.0",
            world_metaphor=metaphor,
        ),
        nodes=nodes,
    )

    installed_id = install_pack(conn, pack_obj.model_dump())
    # Marcar source_type='local' conservando status='active' y engine_type
    conn.execute(
        "UPDATE courses SET source_type = 'local', status = 'active', engine_type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
        (effective_engine, installed_id),
    )
    total_chunks = index_chunks_in_fts(conn, installed_id, all_chunks)

    return {
        "course_id": installed_id,
        "course_code": clean_code,
        "title": clean_title,
        "engine_type": effective_engine,
        "detected_language": effective_lang,
        "status": "active",
        "mode": "replace",
        "added_nodes": len(pack_obj.nodes),
        "node_count": len(pack_obj.nodes),
        "chunks_indexed": total_chunks,
        "processed_files": processed_files,
        "skipped_files": skipped_files,
        "provider": provider_used,
        "world_metaphor": metaphor,
    }


def _resolve_fts_course_keys(conn: sqlite3.Connection, course_id_or_code: str) -> tuple[str, list[str]]:
    row = resolve_course_row(conn, course_id_or_code)
    keys: set[str] = {course_id_or_code}
    clean_slug = re.sub(r"[^a-z0-9]+", "-", course_id_or_code.strip().lower()).strip("-")
    if clean_slug:
        keys.add(f"local-{clean_slug}")
    if row is not None:
        real_id = str(row["id"])
        keys.add(real_id)
        if row["course_code"]:
            keys.add(str(row["course_code"]))
            code_slug = re.sub(r"[^a-z0-9]+", "-", str(row["course_code"]).strip().lower()).strip("-")
            if code_slug:
                keys.add(f"local-{code_slug}")
    else:
        real_id = course_id_or_code
    return real_id, sorted(k for k in keys if k)


def list_course_files(conn: sqlite3.Connection, course_id_or_code: str) -> dict[str, Any]:
    """Lista los archivos unicos indexados en local_chunks_fts para un ramo (por id o course_code)."""
    real_id, keys = _resolve_fts_course_keys(conn, course_id_or_code)
    placeholders = ",".join("?" for _ in keys)
    rows = conn.execute(
        f"""
        SELECT source_file AS filename,
               COUNT(*) AS sections,
               COALESCE(SUM(LENGTH(content)), 0) AS chars
        FROM local_chunks_fts
        WHERE course_id IN ({placeholders})
        GROUP BY source_file
        ORDER BY MIN(rowid) ASC;
        """,
        tuple(keys),
    ).fetchall()
    files = [
        {
            "filename": str(r["filename"]),
            "sections": int(r["sections"]),
            "chars": int(r["chars"]),
        }
        for r in rows
    ]
    return {"course_id": real_id, "files": files}


def delete_course_file(
    conn: sqlite3.Connection,
    course_id_or_code: str,
    filename: str,
) -> dict[str, Any]:
    """Elimina los chunks de un archivo en local_chunks_fts y devuelve cuantos archivos quedan."""
    real_id, keys = _resolve_fts_course_keys(conn, course_id_or_code)
    placeholders = ",".join("?" for _ in keys)
    cur = conn.execute(
        f"DELETE FROM local_chunks_fts WHERE course_id IN ({placeholders}) AND source_file = ?;",
        (*keys, filename),
    )
    conn.commit()
    remaining_info = list_course_files(conn, course_id_or_code)
    return {
        "course_id": real_id,
        "deleted_file": filename,
        "deleted_chunks": cur.rowcount,
        "remaining_files": len(remaining_info["files"]),
        "files": remaining_info["files"],
    }
