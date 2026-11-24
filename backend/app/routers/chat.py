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
    node_title: str | None,
    node_story: str | None,
    node_rubric: list[str],
    fts_snippets: list[str],
    user_msg: str,
) -> str:
    parts: list[str] = []
    if node_title:
        parts.append(f"Estamos en **{node_title}** ({course_title}).")
    else:
        parts.append(f"Revisando **{course_title}** en modo local (sin API key externa configurada).")

    if node_story:
        first_para = node_story.strip().split("\n\n")[0]
        parts.append(f"Sobre tu consulta (*\"{user_msg[:120]}\"*), recuerda la idea central del nodo: {first_para}")

    if node_rubric:
        parts.append("Puntos clave que debes dominar aqui: " + "; ".join(node_rubric[:4]) + ".")

    if fts_snippets:
        parts.append("Extracto relevante de tus apuntes locales: " + fts_snippets[0][:350])

    parts.append(
        "Para respuestas generativas abiertas con IA, configura tu clave gratuita de Groq, Gemini u Ollama en el icono de engranaje de la barra superior."
    )
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

    context_blocks = [f"Ramo: {course_row['title']} ({course_row['course_code'] or real_id})"]
    if node_title:
        context_blocks.append(f"Nodo actual: {node_title}")
    if node_story:
        context_blocks.append(f"Historia del nodo:\n{node_story[:1500]}")
    if node_rubric:
        context_blocks.append("Conceptos de rubrica: " + "; ".join(node_rubric))
    if fts_snippets:
        context_blocks.append("Apuntes locales (FTS5):\n" + "\n".join(fts_snippets))

    system_prompt = (
        "Eres el Tutor Socratico Transversal de Brotal. Responde en espanol claro, directo y conversado, "
        "ayudando al estudiante a razonar sin regalarle respuestas copiables para la evaluacion a ciegas.\n\n"
        + "\n\n".join(context_blocks)
    )

    llm_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for h in recent_history:
        llm_messages.append({"role": h["role"], "content": h["content"]})
    llm_messages.append({"role": "user", "content": user_text})

    try:
        comp = ai_router.complete_chat(llm_messages, preferred_provider=ai_provider, temperature=0.4)
        reply_text = comp.text
        provider_used = comp.provider
    except AiProviderError:
        reply_text = _local_tutor_fallback(
            course_title=course_row["title"],
            node_title=node_title,
            node_story=node_story,
            node_rubric=node_rubric,
            fts_snippets=fts_snippets,
            user_msg=user_text,
        )
        provider_used = "local_fallback"

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
