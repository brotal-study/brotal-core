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
from typing import Any

from app.schemas.pack import CoursePack, PackMetadata
from app.services import ai_router
from app.services.ai_router import AiProviderError, extract_json_object
from app.services.pack_manager import install_pack, resolve_course_row

ALLOWED_EXTENSIONS = {".pdf", ".pptx", ".docx", ".md", ".txt"}
_SEPARATOR_LINE_RE = re.compile(r"(?m)^\s*(?:[-*_]{3,}|={3,})\s*$")


@dataclass
class ExtractedChunk:
    source_file: str
    section_title: str
    content: str


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
    conn.execute("DELETE FROM local_chunks_fts WHERE course_id = ?;", (course_id,))
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


def _strip_bullet_lists(story: str) -> str:
    """Convierte cualquier linea con viñetas en prosa fluida para respetar la regla de historias continuas."""
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
    prose = re.sub(r"\n{3,}", "\n\n", prose).strip()
    return prose


def _fallback_nodes_from_chunks(
    *,
    course_title: str,
    world_metaphor: str,
    chunks: list[ExtractedChunk],
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
        if i == 1:
            parents: list[str] = []
        elif is_theory:
            parents = [f"N{i - 1}"]
        else:
            parents = ["N1"] if i == theory_count + 1 else [f"N{i - 1}"]

        block = "Bloque 1 · Fundamentos Teoricos" if is_theory else "Bloque 2 · Practica y Casos"
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

        story_script = _strip_bullet_lists(
            f"Situemonos en {world_metaphor} para entender por que {title} es una pieza fundamental dentro de "
            f"{course_title}. Cuando observamos el sistema en operacion real, lo primero que salta a la vista es como "
            f"se encadenan las decisiones tecnicas a partir de tus apuntes: {text_snippet[:480]}.\n\n"
            f"Si lo llevas a un escenario concreto dentro de {world_metaphor}, no basta con repetir definiciones "
            f"de memoria. Lo decisivo es seguir la relacion de causa y efecto paso a paso: {key_phrases[0]}. "
            f"Ademas, ten siempre presente que {key_phrases[1]}, porque esa conexion explica como interactuan "
            f"los componentes cuando la carga o la complejidad aumentan.\n\n"
            f"Por eso, al enfrentarte a un caso practico o examen de {course_title} dentro de {world_metaphor}, "
            f"preguntate primero que invariante protege {title} y que ocurriria si esa pieza fallara; asi podras "
            f"diagnosticar y justificar tu solucion con criterio propio."
        )

        nodes.append(
            {
                "id": nid,
                "parent_ids": parents,
                "branch": branch,
                "block": block,
                "title": title,
                "summary": f"Comprension aplicada de {title} en el contexto de {course_title}.",
                "story_script": story_script,
                "eval_prompts": [
                    {
                        "id": "q1",
                        "question": f"Con tus propias palabras y usando la logica de {world_metaphor}, ¿como funciona {title} y que problema resuelve en {course_title}?",
                        "rubric_points": [p[:160] for p in key_phrases[:3]],
                    }
                ],
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


def _generate_nodes_with_ai(
    *,
    course_code: str,
    course_title: str,
    world_metaphor: str,
    chunks: list[ExtractedChunk],
    preferred_provider: str = "auto",
) -> tuple[list[dict[str, Any]], str]:
    """Usa ai_router para sintetizar un arbol profundo de 8..16 nodos (copa theory + raices practice/examenes)."""
    digest_text = _sample_chunks_balanced(chunks)
    files_list = sorted({c.source_file for c in chunks})

    system_prompt = (
        "Eres el Arquitecto Pedagogico de Brotal. Convierte apuntes universitarios en un Arbol de Habilidades "
        "JSON profundo y exigente con ENTRE 8 Y 16 NODOS (si el material es muy corto, minimo 6):\n"
        "- COPA SUPERIOR (`branch: \"theory\"`): entre 6 y 11 nodos conceptuales ordenados por prerequisito y agrupados en bloques claros.\n"
        "- RAICES INFERIORES (`branch: \"practice\"`): entre 3 y 5 nodos explicitos de EXAMENES, CONTROLES, LABS o CASOS REALES "
        "(ej. 'Examen Parcial 1 · ...', 'Caso Practico / Debugging · ...', 'Simulacro Examen Final'), "
        "conectados en `parent_ids` a los nodos 'theory' que ponen a prueba.\n"
        "REGLAS OBLIGATORIAS:\n"
        "1. `story_script` DEBE ser una historia conversada continua de 2 a 3 parrafos (~180 a 240 palabras en total) "
        "usando la metafora del mundo (`world_metaphor`), explicando causa-efecto y que problema real resuelve cada concepto. "
        "PROHIBIDO listas con vinetas y saltos bruscos de extension.\n"
        "2. Ningun titulo (`title`) puede ser una linea separadora (`---`, `===`, `***`) ni tener menos de 3 caracteres alfanumericos.\n"
        "3. El primer nodo 'theory' lleva `parent_ids: []`. Todos los demas conectan `parent_ids` formando un DAG valido.\n"
        "4. Cada nodo DEBE incluir `eval_prompts` con 3 a 4 PREGUNTAS SOCRATICAS A CIEGAS (aplicadas, comparativas o de diagnostico, "
        "nunca triviales) y cada pregunta lleva 2 a 3 `rubric_points` concretos y verificables.\n"
        "5. Cubre TODOS los archivos entregados, no solo el primero.\n"
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
        '      "story_script": "Parrafo 1 conversado...\\n\\nParrafo 2 conversado...",\n'
        '      "eval_prompts": [\n'
        '        {"id": "q1", "question": "...", "rubric_points": ["...", "..."]},\n'
        '        {"id": "q2", "question": "...", "rubric_points": ["...", "..."]},\n'
        '        {"id": "q3", "question": "...", "rubric_points": ["...", "..."]}\n'
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    user_prompt = (
        f"Codigo: {course_code}\n"
        f"Ramo: {course_title}\n"
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

            raw_prompts = n.get("eval_prompts") or []
            clean_prompts = []
            for p_idx, p in enumerate(raw_prompts[:5], start=1):
                pts = [str(x).strip() for x in (p.get("rubric_points") or []) if str(x).strip()]
                if not pts:
                    pts = [f"Explica los conceptos centrales de {n.get('title', nid)}"]
                clean_prompts.append(
                    {
                        "id": str(p.get("id") or f"q{p_idx}"),
                        "question": str(p.get("question") or f"Explica con tus palabras {n.get('title', nid)}."),
                        "rubric_points": pts,
                    }
                )
            if not clean_prompts:
                clean_prompts = [
                    {
                        "id": "q1",
                        "question": f"¿Como explicarias {n.get('title', nid)} y su aplicacion practica?",
                        "rubric_points": [
                            f"Define la idea principal de {n.get('title', nid)}",
                            "Conecta el concepto con un caso practico del ramo",
                        ],
                    }
                ]

            safe_title = _sanitize_title(str(n.get("title") or ""), f"Nodo {idx+1} · {course_title}")
            safe_block = _sanitize_title(
                str(n.get("block") or ""),
                "Bloque Practico" if branch == "practice" else "Bloque Conceptual",
            )
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
) -> dict[str, Any]:
    """Procesa 1..N archivos locales, indexa en FTS5, genera el CoursePack de 6..12 nodos y lo instala como 'active'."""
    if not files:
        raise ValueError("Debes subir al menos 1 archivo (.pdf, .pptx, .docx, .md o .txt).")

    all_chunks: list[ExtractedChunk] = []
    processed_files: list[dict[str, Any]] = []

    for fname, raw_bytes in files:
        file_chunks = extract_chunks_from_bytes(fname, raw_bytes)
        all_chunks.extend(file_chunks)
        processed_files.append(
            {
                "filename": Path(fname).name,
                "sections": len(file_chunks),
                "chars": sum(len(c.content) for c in file_chunks),
            }
        )

    clean_code = course_code.strip().upper() or "LOCAL101"
    clean_title = title.strip() or clean_code
    slug = re.sub(r"[^a-z0-9]+", "-", clean_code.lower()).strip("-") or "course"
    course_id = f"local-{slug}"

    metaphor = (world_metaphor or "").strip() or f"Laboratorio central de {clean_title}"

    nodes, provider_used = _generate_nodes_with_ai(
        course_code=clean_code,
        course_title=clean_title,
        world_metaphor=metaphor,
        chunks=all_chunks,
        preferred_provider=preferred_provider,
    )

    year_now = datetime.now(UTC).year
    pack_obj = CoursePack(
        schema_version="1.0",
        id=course_id,
        course_code=clean_code,
        title=clean_title,
        language="es",
        engine_type="concept_tree",
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
    # Marcar source_type='local' conservando status='active'
    conn.execute(
        "UPDATE courses SET source_type = 'local', status = 'active', updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
        (installed_id,),
    )
    total_chunks = index_chunks_in_fts(conn, installed_id, all_chunks)

    return {
        "course_id": installed_id,
        "course_code": clean_code,
        "title": clean_title,
        "status": "active",
        "node_count": len(pack_obj.nodes),
        "chunks_indexed": total_chunks,
        "processed_files": processed_files,
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
