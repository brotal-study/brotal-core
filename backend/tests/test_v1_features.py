"""Tests unitarios e integracion para v1.0: ai_router, settings, evaluate con IA/fallback, tts, chat e ingest."""
from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import dotenv_path, fixtures_dir
from app.services.ai_router import AiCompletion


def test_settings_providers_get_and_put_chmod_0600(client: TestClient) -> None:
    res = client.get("/api/v1/settings/providers")
    assert res.status_code == 200
    data = res.json()
    assert data["ai_provider"] == "auto"
    assert data["providers"] == {"groq": False, "gemini": False, "ollama": False}
    assert data["active_provider"] == "none"

    put_res = client.put(
        "/api/v1/settings/providers",
        json={
            "ai_provider": "groq",
            "groq_api_key": "gsk_test_fake_secret_value",
            "ollama_url": "http://127.0.0.1:11434",
            "groq_model": "llama-3.3-70b-versatile",
        },
    )
    assert put_res.status_code == 200
    updated = put_res.json()
    assert updated["ai_provider"] == "groq"
    assert updated["providers"]["groq"] is True
    assert updated["providers"]["gemini"] is False
    assert updated["providers"]["ollama"] is True
    assert updated["active_provider"] == "groq"
    assert updated["active_model"] == "llama-3.3-70b-versatile"
    # Jamas debe exponer la key en la respuesta
    assert "gsk_test_fake_secret_value" not in json.dumps(updated)

    env_file = dotenv_path()
    assert env_file.is_file()
    mode = stat.S_IMODE(env_file.stat().st_mode)
    assert mode == 0o600


def test_ai_router_auto_rotation_and_fallback(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import ai_router

    client.put(
        "/api/v1/settings/providers",
        json={
            "ai_provider": "auto",
            "groq_api_key": "gsk_dummy",
            "gemini_api_key": "AIza_dummy",
        },
    )

    calls: list[str] = []

    def fake_groq(*_args: Any, **_kwargs: Any) -> AiCompletion:
        calls.append("groq")
        raise ai_router.AiProviderError("Groq rate limit 429")

    def fake_gemini(*_args: Any, **_kwargs: Any) -> AiCompletion:
        calls.append("gemini")
        return AiCompletion(text='{"ok": true}', provider="gemini", model="gemini-2.5-flash")

    monkeypatch.setattr(ai_router, "call_groq", fake_groq)
    monkeypatch.setattr(ai_router, "call_gemini", fake_gemini)

    comp = ai_router.complete_chat([{"role": "user", "content": "Hola"}], preferred_provider="auto")
    assert comp.provider == "gemini"
    assert calls == ["groq", "gemini"]


def test_socratic_evaluate_with_ai_and_regenerate_story(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ai_router

    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    client.post("/api/v1/courses/install-pack", json=demo_pack)

    def fake_complete_chat(messages: list[dict[str, str]], **kwargs: Any) -> AiCompletion:
        if kwargs.get("json_mode"):
            payload = {
                "score": 6.2,
                "covered_points": ["q1::0"],
                "imprecisions": ["Confundes el modelo OSI de 7 capas con TCP/IP de 4 capas."],
                "re_explanation": "Piensa en el Edificio NetTower: OSI separa Sesion, Presentacion y Aplicacion en 3 pisos distintos.",
            }
            return AiCompletion(text=json.dumps(payload), provider="groq", model="llama-3.3-70b-versatile")
        return AiCompletion(
            text="Imagina el Edificio NetTower en hora punta: cada piso tiene un guardia especializado.\n\nCuando un paquete sube desde la planta baja fisica hasta el piso 7, cada protocolo desencapsula solo su sobre.",
            provider="groq",
            model="llama-3.3-70b-versatile",
        )

    monkeypatch.setattr(ai_router, "complete_chat", fake_complete_chat)

    ev = client.post(
        "/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/evaluate",
        json={
            "answers": [
                {"prompt_id": "q1", "text": "OSI y TCP/IP tienen las mismas capas"},
                {"prompt_id": "q2", "text": "No recuerdo los organismos"},
            ],
            "cooldown_mode": "semester",
        },
    )
    assert ev.status_code == 200
    body = ev.json()
    assert body["score"] == 6.2
    assert body["passed"] is False
    assert body["evaluated_by"] == "groq"
    assert len(body["imprecisions"]) == 1
    assert "NetTower" in body["re_explanation"]

    regen = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/regenerate-story")
    assert regen.status_code == 200
    rbody = regen.json()
    assert rbody["provider"] == "groq"
    assert "hora punta" in rbody["story_script"]


def test_tts_endpoint_caches_mp3_on_disk(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import tts

    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    client.post("/api/v1/courses/install-pack", json=demo_pack)

    synth_calls = 0

    async def fake_run_edge_tts(text: str, voice: str, out_path: Path) -> None:
        nonlocal synth_calls
        synth_calls += 1
        out_path.write_bytes(b"ID3-FAKE-MP3-AUDIO-" + voice.encode("utf-8") + b"-" + text[:16].encode("utf-8"))

    monkeypatch.setattr(tts, "_run_edge_tts", fake_run_edge_tts)

    r1 = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/tts")
    assert r1.status_code == 200
    assert r1.headers["content-type"].startswith("audio/mpeg")
    assert r1.content.startswith(b"ID3-FAKE-MP3-AUDIO-")
    assert synth_calls == 1

    # Segunda llamada debe servir desde cache en disco sin volver a sintetizar
    r2 = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/tts")
    assert r2.status_code == 200
    assert r2.content == r1.content
    assert synth_calls == 1


def test_chat_tutor_endpoints_and_history(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ai_router

    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    client.post("/api/v1/courses/install-pack", json=demo_pack)

    def fake_chat(messages: list[dict[str, str]], **_kwargs: Any) -> AiCompletion:
        sys_msg = messages[0]["content"]
        assert "Modelo OSI" in sys_msg
        return AiCompletion(
            text="Piensa en que capa agrega direcciones IP logicas frente a direcciones MAC fisicas.",
            provider="gemini",
            model="gemini-2.5-flash",
        )

    monkeypatch.setattr(ai_router, "complete_chat", fake_chat)

    post_res = client.post(
        "/api/v1/chat/cl-pucv-inf2324-ccna1",
        json={"message": "¿Cual es la diferencia entre capa 2 y capa 3?", "node_id": "B1-P2"},
    )
    assert post_res.status_code == 200
    pdata = post_res.json()
    assert pdata["provider"] == "gemini"
    assert pdata["user_message"]["role"] == "user"
    assert pdata["assistant_message"]["role"] == "assistant"

    hist_res = client.get("/api/v1/chat/cl-pucv-inf2324-ccna1")
    assert hist_res.status_code == 200
    hist = hist_res.json()
    assert len(hist) == 2

    del_res = client.delete("/api/v1/chat/cl-pucv-inf2324-ccna1")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] == 2
    assert client.get("/api/v1/chat/cl-pucv-inf2324-ccna1").json() == []


def test_ingest_local_md_and_txt_creates_active_course_with_6_to_12_nodes(client: TestClient) -> None:
    md_content = (
        b"# Bloque 1: Clases, Objetos y Encapsulamiento en Java\n"
        b"En Java todo gira en torno a clases que actuan como planos y objetos que viven en el heap. "
        b"El encapsulamiento protege los atributos con modificadores private y expone metodos publicos.\n\n"
        b"# Bloque 2: Herencia y Polimorfismo\n"
        b"Una subclase extiende a su superclase con extends y puede sobrescribir metodos con @Override "
        b"para que el despacho dinamico ejecute la implementacion correcta en tiempo de ejecucion.\n\n"
        b"# Bloque 3: Interfaces y Clases Abstractas\n"
        b"Las interfaces definen contratos puros que cualquier clase puede implementar con implements, "
        b"permitiendo desacoplar componentes y aplicar polimorfismo sin herencia multiple de estado.\n"
    )

    txt_content = (
        b"Colecciones Genericas y Excepciones en Java.\n\n"
        b"ArrayList ofrece acceso indexado rapido mientras HashMap asocia claves unicas a valores mediante hashCode y equals. "
        b"El manejo de errores distingue entre Checked Exceptions que obligan a usar try-catch o throws, "
        b"y RuntimeExceptions para errores de programacion."
    )

    res = client.post(
        "/api/v1/courses/ingest-local",
        data={
            "course_code": "INF2236",
            "title": "Programacion Avanzada en Java",
            "career_id": "cl-pucv-inf-2022",
            "world_metaphor": "Fabrica Modular JVM",
        },
        files=[
            ("files", ("apuntes_poo.md", md_content, "text/markdown")),
            ("files", ("colecciones.txt", txt_content, "text/plain")),
        ],
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["course_code"] == "INF2236"
    assert data["status"] == "active"
    assert 6 <= data["node_count"] <= 12
    assert data["chunks_indexed"] >= 4
    assert len(data["processed_files"]) == 2

    tree_res = client.get(f"/api/v1/courses/{data['course_id']}/tree")
    assert tree_res.status_code == 200
    tree = tree_res.json()
    assert 6 <= len(tree["nodes"]) <= 12
    branches = {n["branch"] for n in tree["nodes"]}
    assert "theory" in branches
    assert "practice" in branches

    # Verificar que la exportacion del pack nunca incluye los archivos originales ni rutas
    exp_res = client.get(f"/api/v1/courses/{data['course_id']}/export")
    assert exp_res.status_code == 200
    exp_str = json.dumps(exp_res.json())
    assert "apuntes_poo.md" not in exp_str
    assert "colecciones.txt" not in exp_str


def test_reingest_cleans_stale_nodes_filters_separators_and_manages_files(client: TestClient) -> None:
    # 1. Instalar un pack con nodos viejos (OLD1, N1, N2, N3, N4, N5) en local-inf2236
    initial_pack = {
        "schema_version": "1.0",
        "id": "local-inf2236",
        "course_code": "INF2236",
        "title": "Programacion Avanzada en Java",
        "language": "es",
        "engine_type": "concept_tree",
        "metadata": {
            "university_id": "local",
            "career_ids": ["cl-pucv-inf-2022"],
            "created_year": 2026,
            "updated_year": 2026,
            "version": "1.0.0",
            "authors": ["Test"],
            "license": "CC-BY-SA-4.0",
            "world_metaphor": "Fabrica JVM",
        },
        "nodes": [
            {
                "id": nid,
                "parent_ids": [] if nid == "OLD1" else ["OLD1"],
                "branch": "theory",
                "block": "Bloque 1",
                "title": f"Titulo {nid}",
                "summary": "Resumen",
                "story_script": "Historia inicial conversada.",
                "eval_prompts": [{"id": "q1", "question": "¿Que es?", "rubric_points": ["Punto clave"]}],
            }
            for nid in ("OLD1", "N1", "N2", "N3", "N4", "N5")
        ],
    }
    inst = client.post("/api/v1/courses/install-pack", json=initial_pack)
    assert inst.status_code == 200

    # Subir best_score de N1 y OLD1 para comprobar que N1 se conserva y OLD1 se limpia al re-ingestar
    ev1 = client.post(
        "/api/v1/study/local-inf2236/N1/evaluate",
        json={"answers": [{"prompt_id": "q1", "text": "Punto clave"}], "score": 9.0},
    )
    assert ev1.status_code == 200
    ev_old = client.post(
        "/api/v1/study/local-inf2236/OLD1/evaluate",
        json={"answers": [{"prompt_id": "q1", "text": "Punto clave"}], "score": 8.5},
    )
    assert ev_old.status_code == 200

    # 2. Re-ingestar con lineas separadoras '---' y '***'
    md_with_separators = (
        b"# ---\n"
        b"---\n"
        b"Arquitectura de Clases y Encapsulamiento en Java con modificadores de acceso y metodos seguros.\n\n"
        b"## ===\n"
        b"***\n"
        b"Polimorfismo dinamico e interfaces desacopladas para diseno modular en sistemas empresariales.\n"
    )
    txt_extra = (
        b"---\n"
        b"Manejo de Excepciones Checked y Runtime en flujos transaccionales de entrada y salida.\n"
    )

    re_res = client.post(
        "/api/v1/courses/ingest-local",
        data={
            "course_code": "INF2236",
            "title": "Programacion Avanzada en Java",
            "career_id": "cl-pucv-inf-2022",
            "world_metaphor": "Fabrica Modular JVM",
        },
        files=[
            ("files", ("guia_1.md", md_with_separators, "text/markdown")),
            ("files", ("guia_2.txt", txt_extra, "text/plain")),
        ],
    )
    assert re_res.status_code == 200

    tree = client.get("/api/v1/courses/INF2236/tree").json()
    node_ids = {n["id"] for n in tree["nodes"]}
    assert "OLD1" not in node_ids
    assert "OLD1" not in tree["progress"]
    # N1 sigue existiendo y conserva su best_score previo
    assert "N1" in node_ids
    assert tree["progress"]["N1"]["best_score"] == 9.0

    # Ningun nodo puede llamarse '---', '===' ni tener menos de 3 caracteres alfanumericos
    for n in tree["nodes"]:
        assert n["title"] not in ("---", "===", "***")
        assert sum(1 for c in n["title"] if c.isalnum()) >= 3

    # 3. GET /api/v1/courses/{course_id}/files funciona tanto por course_code como por course_id
    files_by_code = client.get("/api/v1/courses/INF2236/files")
    assert files_by_code.status_code == 200
    f_list = files_by_code.json()["files"]
    assert [f["filename"] for f in f_list] == ["guia_1.md", "guia_2.txt"]
    assert all(f["sections"] >= 1 and f["chars"] > 10 for f in f_list)

    # 4. DELETE /api/v1/courses/{course_id}/files/{filename}
    del_res = client.delete("/api/v1/courses/INF2236/files/guia_1.md")
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["deleted_file"] == "guia_1.md"
    assert del_data["remaining_files"] == 1
    assert [f["filename"] for f in del_data["files"]] == ["guia_2.txt"]


def test_regenerate_questions_endpoint_updates_node_prompts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ai_router

    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    client.post("/api/v1/courses/install-pack", json=demo_pack)

    tree_before = client.get("/api/v1/courses/cl-pucv-inf2324-ccna1/tree").json()
    node_before = next(n for n in tree_before["nodes"] if n["id"] == "B1-P2")
    orig_prompts = node_before["eval_prompts"]

    # Fallback determinista (sin IA) genera preguntas nuevas conservando id y rubric_points
    regen_fallback = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/regenerate-questions")
    assert regen_fallback.status_code == 200
    fb_data = regen_fallback.json()
    assert fb_data["provider"] == "local_fallback"
    assert len(fb_data["eval_prompts"]) == len(orig_prompts)
    for old_p, new_p in zip(orig_prompts, fb_data["eval_prompts"], strict=True):
        assert new_p["id"] == old_p["id"]
        assert new_p["rubric_points"] == old_p["rubric_points"]
        assert new_p["question"] != old_p["question"]

    # Con IA mockeada actualiza eval_prompts_json en SQLite
    def fake_complete_chat(_messages: list[dict[str, str]], **_kwargs: Any) -> AiCompletion:
        payload = {
            "eval_prompts": [
                {
                    "id": p["id"],
                    "question": f"Caso NetTower IA ({p['id']}): ¿como diagnosticarias esta capa?",
                    "rubric_points": p["rubric_points"],
                }
                for p in orig_prompts
            ]
        }
        return AiCompletion(text=json.dumps(payload), provider="groq", model="llama-3.3-70b-versatile")

    monkeypatch.setattr(ai_router, "complete_chat", fake_complete_chat)

    regen_ai = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/regenerate-questions")
    assert regen_ai.status_code == 200
    ai_data = regen_ai.json()
    assert ai_data["provider"] == "groq"
    assert ai_data["eval_prompts"][0]["question"].startswith("Caso NetTower IA")

    tree_after = client.get("/api/v1/courses/cl-pucv-inf2324-ccna1/tree").json()
    node_after = next(n for n in tree_after["nodes"] if n["id"] == "B1-P2")
    assert node_after["eval_prompts"][0]["question"].startswith("Caso NetTower IA")


def test_ingest_local_append_mode_adds_files_and_nodes_preserving_progress(client: TestClient) -> None:
    # 1. Ingesta inicial (replace) con archivo de Semana 1
    week1_md = (
        b"# Bloque 1: Clases y Encapsulamiento en Java\n"
        b"Las clases definen atributos privados y metodos publicos que protegen el invariante de cada objeto en memoria.\n\n"
        b"# Bloque 2: Herencia y Polimorfismo Dinamico\n"
        b"Las subclases especializan el comportamiento con @Override permitiendo despacho dinamico en tiempo de ejecucion.\n"
    )
    res1 = client.post(
        "/api/v1/courses/ingest-local",
        data={
            "course_code": "INF2236",
            "title": "Programacion Avanzada en Java",
            "career_id": "cl-pucv-inf-2022",
            "world_metaphor": "Fabrica Modular JVM",
            "mode": "replace",
        },
        files=[("files", ("semana_1_poo.md", week1_md, "text/markdown"))],
    )
    assert res1.status_code == 200, res1.text
    d1 = res1.json()
    assert d1["mode"] == "replace"
    initial_node_count = d1["node_count"]
    assert initial_node_count >= 6

    # 2. Llevar N1 a mastery_level = 2 y training_reps = 3
    # Primer intento aprobado -> mastery_level = 1 (entra en cooldown)
    ev1 = client.post(
        "/api/v1/study/INF2236/N1/evaluate",
        json={"answers": [{"prompt_id": "q1", "text": "Respuesta completa"}], "score": 9.0, "cooldown_mode": "urgency"},
    )
    assert ev1.status_code == 200
    assert ev1.json()["progress"]["mastery_level"] == 1

    # Tres intentos durante cooldown -> suben training_reps a 3 sin subir mastery_level
    for rep in range(1, 4):
        ev_rep = client.post(
            "/api/v1/study/INF2236/N1/evaluate",
            json={"answers": [{"prompt_id": "q1", "text": "Practica en cooldown"}], "score": 8.5, "cooldown_mode": "urgency"},
        )
        assert ev_rep.status_code == 200
        assert ev_rep.json()["progress"]["mastery_level"] == 1
        assert ev_rep.json()["progress"]["training_reps"] == rep

    # Expirar cooldown en SQLite para subir a mastery_level = 2
    from app.db.database import _connect

    conn = _connect()
    try:
        conn.execute(
            "UPDATE node_progress SET next_review_at = '2020-01-01T00:00:00Z' WHERE course_id = ? AND node_id = 'N1';",
            (d1["course_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    ev2 = client.post(
        "/api/v1/study/INF2236/N1/evaluate",
        json={"answers": [{"prompt_id": "q1", "text": "Validacion tras cooldown"}], "score": 9.5, "cooldown_mode": "urgency"},
    )
    assert ev2.status_code == 200
    assert ev2.json()["progress"]["mastery_level"] == 2
    assert ev2.json()["progress"]["training_reps"] == 3

    # 3. Ingesta incremental (mode="append") con archivo de Semana 2
    week2_txt = (
        b"# Concurrencia, Hilos y Sincronizacion en la JVM\n"
        b"Los hilos comparten el heap y requieren bloques synchronized o Locks explicitos para evitar condiciones de carrera.\n\n"
        b"# Ejecutores, Futures y CompletableFuture\n"
        b"ExecutorService administra pools de hilos reutilizables mientras CompletableFuture encadena tareas asincronas sin bloquear.\n"
    )
    res2 = client.post(
        "/api/v1/courses/ingest-local",
        data={
            "course_code": "INF2236",
            "title": "Programacion Avanzada en Java",
            "career_id": "cl-pucv-inf-2022",
            "mode": "append",
        },
        files=[("files", ("semana_2_concurrencia.md", week2_txt, "text/markdown"))],
    )
    assert res2.status_code == 200, res2.text
    d2 = res2.json()
    assert d2["mode"] == "append"
    assert d2["added_nodes"] >= 2
    assert d2["node_count"] == initial_node_count + d2["added_nodes"]

    # 4. GET /files suma ambos archivos
    files_res = client.get("/api/v1/courses/INF2236/files")
    assert files_res.status_code == 200
    filenames = [f["filename"] for f in files_res.json()["files"]]
    assert filenames == ["semana_1_poo.md", "semana_2_concurrencia.md"]

    # 5. GET /tree contiene los nodos nuevos conectados y preserva N1 en mastery_level=2 y training_reps=3
    tree_res = client.get("/api/v1/courses/INF2236/tree")
    assert tree_res.status_code == 200
    tree = tree_res.json()
    assert len(tree["nodes"]) == d2["node_count"]
    all_node_ids = {n["id"] for n in tree["nodes"]}
    new_nodes = [n for n in tree["nodes"] if n["id"].startswith("A")]
    assert len(new_nodes) == d2["added_nodes"]
    for nn in new_nodes:
        assert len(nn["parent_ids"]) >= 1
        assert all(pid in all_node_ids for pid in nn["parent_ids"])

    n1_prog = tree["progress"]["N1"]
    assert n1_prog["mastery_level"] == 2
    assert n1_prog["training_reps"] == 3
    assert n1_prog["best_score"] == 9.5


def test_tts_timings_endpoint_and_cleanup_on_regenerate(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import tts

    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    client.post("/api/v1/courses/install-pack", json=demo_pack)

    async def fake_run_edge_tts_with_timings(text: str, voice: str, out_path: Path) -> list[dict[str, Any]]:
        out_path.write_bytes(b"ID3-FAKE-MP3-" + voice.encode("utf-8"))
        sentences = tts.split_story_sentences(text)
        return [
            {"text": s, "start": round(i * 2.5, 3), "end": round((i + 1) * 2.5, 3)}
            for i, s in enumerate(sentences)
        ]

    monkeypatch.setattr(tts, "_run_edge_tts", fake_run_edge_tts_with_timings)

    tts_res = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/tts")
    assert tts_res.status_code == 200

    timings_res = client.get("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/tts-timings")
    assert timings_res.status_code == 200
    tdata = timings_res.json()
    assert tdata["course_id"] == "cl-pucv-inf2324-ccna1"
    assert tdata["node_id"] == "B1-P2"
    assert len(tdata["timings"]) >= 2
    assert tdata["timings"][0]["start"] == 0.0
    assert tdata["timings"][0]["end"] == 2.5

    # Al regenerar la historia se limpia el cache (.mp3 y .timings.json) de la historia anterior
    regen_res = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/regenerate-story")
    assert regen_res.status_code == 200
    after_timings = client.get("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/tts-timings").json()
    assert after_timings["timings"] == []
    # Incluso sin cache en disco, words devuelve tiempos proporcionales por palabra (nunca vacio)
    assert len(after_timings["words"]) >= 10
    assert after_timings["words"][0]["start"] == 0.0
    assert after_timings["words"][0]["end"] > 0.0


def test_chat_tutor_injects_nodes_index_and_extracts_suggested_nodes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ai_router

    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    client.post("/api/v1/courses/install-pack", json=demo_pack)

    def fake_chat(messages: list[dict[str, str]], **_kwargs: Any) -> AiCompletion:
        sys_msg = messages[0]["content"]
        # Verifica que el indice de nodos del ramo fue inyectado en el system_prompt
        assert "[[node:B1-P1|" in sys_msg
        assert "[[node:B1-P2|" in sys_msg
        assert "PROHIBIDO usar emojis" in sys_msg
        return AiCompletion(
            text=(
                "Para dominar las capas revisa primero [[node:B1-P1|Topologias y Dispositivos]] "
                "y luego profundiza en [[node:B1-P2|Modelo OSI vs TCP/IP]]."
            ),
            provider="groq",
            model="llama-3.3-70b-versatile",
        )

    monkeypatch.setattr(ai_router, "complete_chat", fake_chat)

    res = client.post(
        "/api/v1/chat/cl-pucv-inf2324-ccna1",
        json={"message": "¿Donde puedo aprender el modelo OSI?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["suggested_nodes"]) == 2
    assert data["suggested_nodes"][0]["id"] == "B1-P1"
    assert data["suggested_nodes"][1]["id"] == "B1-P2"


def test_pedagogical_styles_in_regenerate_story_and_questions(client: TestClient) -> None:
    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    client.post("/api/v1/courses/install-pack", json=demo_pack)

    # Cambiar perfil a explanation_style='direct' y question_style='direct'
    p1 = client.patch(
        "/api/v1/profile",
        json={"explanation_style": "direct", "question_style": "direct"},
    )
    assert p1.status_code == 200

    s_direct = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/regenerate-story")
    assert s_direct.status_code == 200
    assert "Imagina" not in s_direct.json()["story_script"]

    q_direct = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/regenerate-questions")
    assert q_direct.status_code == 200
    assert len(q_direct.json()["eval_prompts"]) >= 1

    # Cambiar perfil a explanation_style='structured' y question_style='scenario'
    p2 = client.patch(
        "/api/v1/profile",
        json={"explanation_style": "structured", "question_style": "scenario"},
    )
    assert p2.status_code == 200

    s_struct = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/regenerate-story")
    assert s_struct.status_code == 200
    story_txt = s_struct.json()["story_script"]
    assert "Concepto central:" in story_txt
    assert "Causa y efecto:" in story_txt
    assert "Ejemplo concreto:" in story_txt

    q_scen = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/regenerate-questions")
    assert q_scen.status_code == 200
    assert q_scen.json()["eval_prompts"][0]["question"] != q_direct.json()["eval_prompts"][0]["question"]


def test_tts_word_boundary_timings_saved_and_returned(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import tts

    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    client.post("/api/v1/courses/install-pack", json=demo_pack)

    async def fake_run_edge_tts_words(text: str, voice: str, out_path: Path) -> dict[str, Any]:
        out_path.write_bytes(b"ID3-WORDS-MP3-" + voice.encode("utf-8"))
        words = [w for w in text.split() if w][:6]
        word_events = [
            {"text": w, "start": round(i * 0.3, 3), "end": round((i + 1) * 0.3, 3)}
            for i, w in enumerate(words)
        ]
        sentences = tts._group_word_boundaries_into_sentences(text, word_events)
        return {"sentences": sentences, "words": word_events}

    monkeypatch.setattr(tts, "_run_edge_tts", fake_run_edge_tts_words)

    synth = client.post("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P1/tts")
    assert synth.status_code == 200

    t_res = client.get("/api/v1/study/cl-pucv-inf2324-ccna1/B1-P1/tts-timings")
    assert t_res.status_code == 200
    payload = t_res.json()
    assert len(payload["words"]) == 6
    assert payload["words"][0]["start"] == 0.0
    assert payload["words"][0]["end"] == 0.3
    assert len(payload["sentences"]) >= 1
