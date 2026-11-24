"""Router del Chat Tutor Transversal por Ramo /api/v1/chat/{course_id} (v1.0).

Contrato:
- GET /api/v1/chat/{course_id}: devuelve historial reciente de chat_messages del ramo.
- POST /api/v1/chat/{course_id}: recibe {message, node_id?}, usa historia del nodo + chunks FTS5 del ramo +
  ultimas 10 interacciones de chat_messages, responde con ai_router (o fallback contextual offline) y persiste.
- DELETE /api/v1/chat/{course_id}: limpia el historial de chat del ramo.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.db.database import get_conn
from app.services import ai_router
from app.services.ai_router import AiProviderError
from app.services.pack_manager import resolve_course_row

router = APIRouter(tags=["chat"])

DbConn = Annotated[sqlite3.Connection, Depends(get_conn)]


class SuggestedNode(BaseModel):
    id: str
    title: str


class ChatMessageOut(BaseModel):
    id: int
    course_id: str
    node_id: str | None = None
    role: str
    content: str
    created_at: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    node_id: str | None = None


class ChatResponse(BaseModel):
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut
    provider: str
    suggested_nodes: list[SuggestedNode] = Field(default_factory=list)


_NODE_LINK_RE = re.compile(r"\[\[node:([^|\]]+)\|([^\]]+)\]\]")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)


def _strip_emojis(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


def _load_course_nodes_index(conn: sqlite3.Connection, course_id: str) -> list[dict[str, str | int]]:
    rows = conn.execute(
        """
        SELECT cn.id,
               cn.title,
               cn.branch,
               COALESCE( cn.summary, '' ) AS summary,
               COALESCE( np.mastery_level, 0 ) AS mastery_level
        FROM course_nodes cn
        LEFT JOIN node_progress np
          ON np.course_id = cn.course_id AND np.node_id = cn.id
        WHERE cn.course_id = ?
        ORDER BY cn.rowid ASC;
        """,
        (course_id,),
    ).fetchall()
    return [
        {
            "id": str(r["id"]),
            "title": str(r["title"]),
            "branch": str(r["branch"]),
            "summary": str(r["summary"]),
            "mastery_level": int(r["mastery_level"]),
        }
        for r in rows
    ]


def _extract_suggested_nodes(
    text: str,
    nodes_by_id: dict[str, str],
) -> list[SuggestedNode]:
    seen: set[str] = set()
    suggested: list[SuggestedNode] = []
    for match in _NODE_LINK_RE.finditer(text):
        raw_id = match.group(1).strip()
        raw_title = match.group(2).strip()
        if not raw_id or raw_id in seen:
            continue
        seen.add(raw_id)
        resolved_title = nodes_by_id.get(raw_id, raw_title or raw_id)
        suggested.append(SuggestedNode(id=raw_id, title=resolved_title))
    return suggested


def _search_fts_chunks(conn: sqlite3.Connection, course_id: str, course_code: str | None, query: str) -> list[str]:
    tokens = [w for w in re.split(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]+", query) if len(w) >= 3][:6]
    snippets: list[str] = []

    if tokens:
        fts_query = " OR ".join(f'"{t}"' for t in tokens)
        try:
            rows = conn.execute(
                """
                SELECT source_file, section_title, content
                FROM local_chunks_fts
                WHERE local_chunks_fts MATCH ? AND (course_id = ? OR course_id = ?)
                LIMIT 3;
                """,
                (fts_query, course_id, course_code or course_id),
            ).fetchall()
            for r in rows:
                snippets.append(f"[{r['source_file']} · {r['section_title']}] {r['content'][:600]}")
        except sqlite3.OperationalError:
            snippets = []

    if not snippets:
        rows = conn.execute(
            """
            SELECT source_file, section_title, content
            FROM local_chunks_fts
            WHERE course_id = ? OR course_id = ?
            LIMIT 2;
            """,
            (course_id, course_code or course_id),
        ).fetchall()
        for r in rows:
            snippets.append(f"[{r['source_file']} · {r['section_title']}] {r['content'][:500]}")

    return snippets


def _local_tutor_fallback(
    *,
    course_title: str,
    node_id: str | None,
    node_title: str | None,
    node_story: str | None,
    node_rubric: list[str],
    fts_snippets: list[str],
    course_nodes: list[dict[str, str | int]],
    user_msg: str,
) -> str:
    parts: list[str] = []
    if node_id and node_title:
        parts.append(f"Nodo actual: [[node:{node_id}|{node_title}]] ({course_title}).")
    elif node_title:
        parts.append(f"Nodo actual: **{node_title}** ({course_title}).")
    else:
        parts.append(f"Ramo: **{course_title}** (modo local sin API key externa).")

    # Buscar nodos del arbol relacionados con la consulta del usuario
    query_tokens = [w.lower() for w in re.split(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]+", user_msg) if len(w) >= 3]
    matched_nodes: list[dict[str, str | int]] = []
    for cn in course_nodes:
        haystack = f"{cn['id']} {cn['title']} {cn.get('summary', '')}".lower()
        if query_tokens and any(tok in haystack for tok in query_tokens):
            matched_nodes.append(cn)
    if not matched_nodes and course_nodes:
        matched_nodes = course_nodes[:2]

    if matched_nodes:
        links = ", ".join(f"[[node:{cn['id']}|{cn['title']}]]" for cn in matched_nodes[:3])
        parts.append(f"Nodos recomendados en el arbol: {links}.")

    if node_story:
        first_para = node_story.strip().split("\n\n")[0]
        parts.append(f"Idea central: {first_para}")

    if node_rubric:
        parts.append("Criterios clave: " + "; ".join(node_rubric[:4]) + ".")

    if fts_snippets:
        parts.append("Apuntes locales: " + fts_snippets[0][:350])

    return "\n\n".join(parts)


@router.get("/chat/{course_id}", response_model=list[ChatMessageOut])
def get_chat_history(
    course_id: str,
    conn: DbConn,
) -> list[ChatMessageOut]:
    course_row = resolve_course_row(conn, course_id)
    if course_row is None:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    real_id = course_row["id"]
    rows = conn.execute(
        """
        SELECT id, course_id, node_id, role, content, created_at
        FROM chat_messages
        WHERE course_id = ?
        ORDER BY id ASC
        LIMIT 100;
        """,
        (real_id,),
    ).fetchall()
    return [ChatMessageOut(**dict(r)) for r in rows]


@router.post("/chat/{course_id}", response_model=ChatResponse)
def post_chat_message(
    course_id: str,
    body: ChatRequest,
    conn: DbConn,
) -> ChatResponse:
    course_row = resolve_course_row(conn, course_id)
    if course_row is None:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    real_id = course_row["id"]
    user_text = body.message.strip()
    if not user_text:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    node_title: str | None = None
    node_story: str | None = None
    node_rubric: list[str] = []
    if body.node_id:
        nrow = conn.execute(
            "SELECT title, summary, story_script, eval_prompts_json FROM course_nodes WHERE course_id = ? AND id = ?;",
            (real_id, body.node_id),
        ).fetchone()
        if nrow is not None:
            node_title = nrow["title"]
            node_story = nrow["story_script"]
            try:
                prompts = json.loads(nrow["eval_prompts_json"] or "[]")
                node_rubric = [pt for q in prompts for pt in q.get("rubric_points", [])]
            except json.JSONDecodeError:
                node_rubric = []

    fts_snippets = _search_fts_chunks(conn, real_id, course_row["course_code"], user_text)

    # Ultimas 10 interacciones previas
    history_rows = conn.execute(
        """
        SELECT role, content
        FROM chat_messages
        WHERE course_id = ?
        ORDER BY id DESC
        LIMIT 10;
        """,
        (real_id,),
    ).fetchall()
    recent_history = list(reversed(history_rows))

    # Guardar mensaje del usuario
    cur_user = conn.execute(
        """
        INSERT INTO chat_messages (course_id, node_id, role, content)
        VALUES (?, ?, 'user', ?);
        """,
        (real_id, body.node_id, user_text),
    )
    user_msg_id = cur_user.lastrowid
    user_row = conn.execute("SELECT * FROM chat_messages WHERE id = ?;", (user_msg_id,)).fetchone()
    assert user_row is not None

    conn.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1);")
    prof = conn.execute("SELECT ai_provider FROM user_profile WHERE id = 1;").fetchone()
    ai_provider = prof["ai_provider"] if prof else "auto"

    course_nodes = _load_course_nodes_index(conn, real_id)
    nodes_by_id = {str(n["id"]): str(n["title"]) for n in course_nodes}
    nodes_index_lines = [
        f"- [[node:{n['id']}|{n['title']}]] (rama: {n['branch']}, dominio: {n['mastery_level']}/3)"
        for n in course_nodes
    ]

    context_blocks = [f"Ramo: {course_row['title']} ({course_row['course_code'] or real_id})"]
    if nodes_index_lines:
        context_blocks.append("Indice completo de nodos del arbol del ramo:\n" + "\n".join(nodes_index_lines))
    if node_title and body.node_id:
        context_blocks.append(f"Nodo actual en pantalla: [[node:{body.node_id}|{node_title}]]")
    elif node_title:
        context_blocks.append(f"Nodo actual en pantalla: {node_title}")
    if node_story:
        context_blocks.append(f"Historia del nodo actual:\n{node_story[:1500]}")
    if node_rubric:
        context_blocks.append("Conceptos de rubrica del nodo actual: " + "; ".join(node_rubric))
    if fts_snippets:
        context_blocks.append("Apuntes locales (FTS5):\n" + "\n".join(fts_snippets))

    system_prompt = (
        "Eres el Tutor Tecnico de Brotal. Responde en espanol de forma DIRECTA, BREVE Y AL GRANO.\n"
        "REGLAS ESTRICTAS:\n"
        "1. PROHIBIDO usar saludos largos, frases de cortesia de relleno o preguntas introductorias innecesarias. "
        "Empieza la primera linea respondiendo directamente la duda.\n"
        "2. PROHIBIDO usar emojis.\n"
        "3. Usa Markdown limpio (negritas, listas puntuales o bloques de codigo cortos cuando aporten claridad).\n"
        "4. Cada vez que menciones, relaciones o recomiendes un nodo del ramo (por ejemplo si preguntan donde aprender "
        "o repasar un tema), citalo SIEMPRE con el formato exacto [[node:<ID>|<Titulo>]] "
        "(ejemplo: [[node:T5|Direccionamiento IPv6]]).\n"
        "5. Explica con precision tecnica sin entregar respuestas redactadas listas para copiar y pegar en la evaluacion a ciegas.\n\n"
        + "\n\n".join(context_blocks)
    )

    llm_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for h in recent_history:
        llm_messages.append({"role": h["role"], "content": h["content"]})
    llm_messages.append({"role": "user", "content": user_text})

    try:
        comp = ai_router.complete_chat(llm_messages, preferred_provider=ai_provider, temperature=0.3)
        reply_text = _strip_emojis(comp.text)
        provider_used = comp.provider
    except AiProviderError:
        reply_text = _local_tutor_fallback(
            course_title=course_row["title"],
            node_id=body.node_id if node_title else None,
            node_title=node_title,
            node_story=node_story,
            node_rubric=node_rubric,
            fts_snippets=fts_snippets,
            course_nodes=course_nodes,
            user_msg=user_text,
        )
        provider_used = "local_fallback"

    suggested_nodes = _extract_suggested_nodes(reply_text, nodes_by_id)

    cur_asst = conn.execute(
        """
        INSERT INTO chat_messages (course_id, node_id, role, content)
        VALUES (?, ?, 'assistant', ?);
        """,
        (real_id, body.node_id, reply_text),
    )
    asst_msg_id = cur_asst.lastrowid
    conn.commit()
    asst_row = conn.execute("SELECT * FROM chat_messages WHERE id = ?;", (asst_msg_id,)).fetchone()
    assert asst_row is not None

    return ChatResponse(
        user_message=ChatMessageOut(**dict(user_row)),
        assistant_message=ChatMessageOut(**dict(asst_row)),
        provider=provider_used,
        suggested_nodes=suggested_nodes,
    )


@router.delete("/chat/{course_id}")
def delete_chat_history(
    course_id: str,
    conn: DbConn,
) -> dict[str, str | int]:
    course_row = resolve_course_row(conn, course_id)
    if course_row is None:
        raise HTTPException(status_code=404, detail=f"Course '{course_id}' not found")

    real_id = course_row["id"]
    cur = conn.execute("DELETE FROM chat_messages WHERE course_id = ?;", (real_id,))
    conn.commit()
    return {"course_id": real_id, "deleted": cur.rowcount}
