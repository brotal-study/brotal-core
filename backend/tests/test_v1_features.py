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


def test_detect_engine_type_java_sql_and_concept_tree() -> None:
    from app.services.ingest import ExtractedChunk, detect_engine_type

    java_chunks = [
        ExtractedChunk(
            source_file="Guia1.md",
            section_title="Herencia y Polimorfismo",
            content="public class Animal { public static void main(String[] args) { System.out.println(1); } }",
        )
    ]
    eng_java, lang_java = detect_engine_type("INF2236", "Programacion Avanzada en Java", java_chunks)
    assert eng_java == "code_lab"
    assert lang_java == "java"

    sql_chunks = [
        ExtractedChunk(
            source_file="Consultas.md",
            section_title="Modelo Relacional",
            content="CREATE TABLE alumnos (id INT PRIMARY KEY); SELECT nombre FROM alumnos INNER JOIN cursos GROUP BY id;",
        )
    ]
    eng_sql, lang_sql = detect_engine_type("INF2240", "Bases de Datos Relacionales", sql_chunks)
    assert eng_sql == "code_lab"
    assert lang_sql == "sql"

    concept_chunks = [
        ExtractedChunk(
            source_file="Redes.md",
            section_title="Capas OSI",
            content="El modelo OSI divide las comunicaciones de red en siete capas jerarquicas desde la capa fisica.",
        )
    ]
    eng_concept, lang_concept = detect_engine_type("INF2324", "Redes de Computadores", concept_chunks)
    assert eng_concept == "concept_tree"
    assert lang_concept == "text"


def test_code_lab_ingest_generates_code_challenges_and_tree_returns_engine_type(client: TestClient) -> None:
    java_notes = (
        b"# Clases, Constructores y Encapsulamiento en Java\n"
        b"public class CuentaBancaria { private double saldo; public void depositar(double monto) {} }\n"
        b"El encapsulamiento protege el invariante del objeto usando atributos private y metodos publicos.\n\n"
        b"# Herencia, Polimorfismo y Sobrescritura con @Override\n"
        b"class CuentaAhorro extends CuentaBancaria implements Auditable { @Override public void depositar(double m) {} }\n"
        b"El despacho dinamico en la JVM invoca la implementacion real del objeto en el heap.\n\n"
        b"# Excepciones Checked vs RuntimeException\n"
        b"Los bloques try { ... } catch (IOException e) { ... } obligan a declarar o capturar errores verificados.\n"
    )

    res = client.post(
        "/api/v1/courses/ingest-local",
        data={
            "course_code": "INF2236",
            "title": "Programacion Orientada a Objetos en Java",
            "career_id": "cl-pucv-inf-2022",
            "engine_type": "auto",
        },
        files=[("files", ("apuntes_java.md", java_notes, "text/markdown"))],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["engine_type"] == "code_lab"
    assert body["detected_language"] == "java"

    tree_res = client.get("/api/v1/courses/INF2236/tree")
    assert tree_res.status_code == 200
    tree = tree_res.json()
    assert tree["engine_type"] == "code_lab"
    assert len(tree["nodes"]) >= 6

    theory_nodes = [n for n in tree["nodes"] if n["branch"] == "theory"]
    practice_nodes = [n for n in tree["nodes"] if n["branch"] == "practice"]
    assert len(theory_nodes) >= 4
    assert len(practice_nodes) >= 1

    # Nodos theory combinan concept + desafios de codigo con starter_code
    t_prompts = theory_nodes[0]["eval_prompts"]
    t_types = {p["challenge_type"] for p in t_prompts}
    assert "concept" in t_types
    assert bool(t_types & {"debug", "trace", "implement"})
    code_prompts = [p for p in t_prompts if p["challenge_type"] in ("debug", "trace", "implement")]
    assert all(p["language"] == "java" and p["starter_code"] is not None for p in code_prompts)
    # debug y trace llevan el codigo completo; implement lleva comentario breve de 1 linea o vacio (sin esqueleto resuelto)
    for p in code_prompts:
        if p["challenge_type"] in ("debug", "trace"):
            assert len(p["starter_code"]) > 20 and "class " in p["starter_code"]
        elif p["challenge_type"] == "implement":
            assert "TODO" not in p["starter_code"]

    # Nodos practice tienen desafios debug/implement con starter_code cumpliendo la regla
    p_prompts = practice_nodes[0]["eval_prompts"]
    assert all(p["challenge_type"] in ("debug", "implement", "trace") for p in p_prompts)
    for p in p_prompts:
        if p["challenge_type"] == "debug":
            assert p["starter_code"] and "class " in p["starter_code"]
        elif p["challenge_type"] == "implement":
            assert p["starter_code"] is not None and "TODO" not in p["starter_code"]

    # Regenerar preguntas en code_lab produce nuevo starter_code distinto
    prev_debug = next(p for p in t_prompts if p["challenge_type"] == "debug")
    regen_res = client.post(f"/api/v1/study/INF2236/{theory_nodes[0]['id']}/regenerate-questions")
    assert regen_res.status_code == 200
    regen_prompts = regen_res.json()["eval_prompts"]
    new_debug = next(p for p in regen_prompts if p["id"] == prev_debug["id"])
    assert new_debug["challenge_type"] == "debug"
    assert new_debug["starter_code"] != prev_debug["starter_code"]


def test_evaluate_with_ai_normalizes_score_to_10_when_100_percent_covered_without_imprecisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ai_router

    def fake_complete_chat(_messages: list[dict[str, str]], **_kwargs: Any) -> AiCompletion:
        # El LLM devuelve 9.5 aunque cubrio todos los rubric_points y no puso imprecisions
        payload = {
            "score": 9.5,
            "covered_points": ["q1::0", "q1::1", "q2::0"],
            "imprecisions": [],
            "re_explanation": "",
        }
        return AiCompletion(text=json.dumps(payload), provider="groq", model="llama-3.3-70b-versatile")

    monkeypatch.setattr(ai_router, "complete_chat", fake_complete_chat)

    res = ai_router.evaluate_with_ai(
        node_title="Arreglos y Constructores en Java",
        story_script="En Java los arreglos tienen tamano fijo y los constructores inicializan el estado.",
        eval_prompts=[
            {"id": "q1", "question": "Explica arreglos", "rubric_points": ["Tamano fijo", "Indices 0..n-1"]},
            {"id": "q2", "question": "Implementa constructor", "rubric_points": ["Inicializa atributos"]},
        ],
        answers_by_prompt={"q1": "Tamano fijo e indices desde 0", "q2": "public Foo() { this.x = 1; }"},
        engine_type="code_lab",
    )
    assert res["score"] == 10.0
    assert res["imprecisions"] == []
    assert set(res["covered_points"]) == {"q1::0", "q1::1", "q2::0"}


def test_career_detail_includes_course_progress_summary(client: TestClient) -> None:
    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    inst = client.post("/api/v1/courses/install-pack", json=demo_pack)
    assert inst.status_code == 200

    # Evaluar B1-P1 una vez para que cuente como 'started' (mastery_level = 1)
    ev = client.post(
        "/api/v1/study/cl-pucv-inf2324-ccna1/B1-P1/evaluate",
        json={"answers": [{"prompt_id": "q1", "text": "Respuesta completa"}], "score": 9.0},
    )
    assert ev.status_code == 200

    career_res = client.get("/api/v1/careers/cl-pucv-inf-2022")
    assert career_res.status_code == 200
    career_data = career_res.json()
    assert "course_progress" in career_data
    prog_inf2324 = career_data["course_progress"].get("INF2324")
    assert prog_inf2324 is not None
    assert prog_inf2324["total"] == len(demo_pack["nodes"])
    assert prog_inf2324["started"] == 1
    assert prog_inf2324["mastered"] == 0


def test_exam_route_generation_persistence_and_uncovered_topics(client: TestClient) -> None:
    from datetime import date, timedelta

    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    inst = client.post("/api/v1/courses/install-pack", json=demo_pack)
    assert inst.status_code == 200
    cid = "cl-pucv-inf2324-ccna1"

    missing = client.get(f"/api/v1/courses/{cid}/exam-route")
    assert missing.status_code == 404

    exam_dt = (date.today() + timedelta(days=5)).isoformat()
    created = client.post(
        f"/api/v1/courses/{cid}/exam-route",
        json={
            "exam_date": exam_dt,
            "hours_per_day": 3.0,
            "goal": "Necesito 3.5 para aprobar con 4.0",
            "exam_topics": "Ethernet y direcciones MAC\nBGP multihoming avanzado",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["course_id"] == cid
    assert body["exam_date"] == exam_dt
    assert body["days_left"] == 5
    assert body["recommended_cooldown_mode"] == "urgency"
    assert len(body["days"]) >= 1
    valid_ids = {n["id"] for n in demo_pack["nodes"]}
    step_ids = [s["node_id"] for d in body["days"] for s in d["steps"] if s["node_id"]]
    assert step_ids
    assert all(nid in valid_ids for nid in step_ids)
    assert any("BGP" in t for t in body["uncovered_topics"])

    fetched = client.get(f"/api/v1/courses/{cid}/exam-route")
    assert fetched.status_code == 200
    assert fetched.json()["strategy_summary"] == body["strategy_summary"]
    assert fetched.json()["days"] == body["days"]


def test_exam_route_with_ai_sanitizes_unknown_node_ids(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import date, timedelta

    from app.services import ai_router

    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    inst = client.post("/api/v1/courses/install-pack", json=demo_pack)
    assert inst.status_code == 200
    cid = "cl-pucv-inf2324-ccna1"
    valid_first = demo_pack["nodes"][0]["id"]
    exam_dt = (date.today() + timedelta(days=3)).isoformat()

    def fake_complete_chat(_messages: list[dict[str, str]], **_kwargs: Any) -> AiCompletion:
        payload = {
            "strategy_summary": "Enfócate primero en bases y luego en el simulacro práctico.",
            "recommended_cooldown_mode": "urgency",
            "days": [
                {
                    "day_label": "Día 1 (Hoy)",
                    "date": date.today().isoformat(),
                    "focus": "Fundamentos clave",
                    "steps": [
                        {
                            "node_id": valid_first,
                            "node_title": "Cualquier titulo",
                            "branch": "theory",
                            "action": "study_and_eval",
                            "target_mastery": 1,
                            "estimated_minutes": 40,
                            "reason": "Base obligatoria.",
                        },
                        {
                            "node_id": "NODO-INEXISTENTE-999",
                            "node_title": "Repaso externo puntual",
                            "branch": "review",
                            "action": "custom",
                            "target_mastery": 2,
                            "estimated_minutes": 20,
                            "reason": "Complemento fuera del árbol.",
                        },
                    ],
                }
            ],
            "uncovered_topics": [],
        }
        return AiCompletion(text=json.dumps(payload), provider="groq", model="llama-3.3-70b-versatile")

    monkeypatch.setattr(ai_router, "complete_chat", fake_complete_chat)

    res = client.post(
        f"/api/v1/courses/{cid}/exam-route",
        json={"exam_date": exam_dt, "hours_per_day": 2.5},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "groq"
    steps = data["days"][0]["steps"]
    assert steps[0]["node_id"] == valid_first
    assert steps[0]["node_title"] == demo_pack["nodes"][0]["title"]
    assert steps[1]["node_id"] is None


def test_spa_index_sets_no_cache_header(client: TestClient) -> None:
    res = client.get("/")
    if res.status_code == 200:
        cc = res.headers.get("cache-control", "").lower()
        assert "no-cache" in cc


def test_evaluate_with_ai_and_endpoint_return_prompt_reviews_code_fixes_and_routing_suggestion(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ai_router

    code_pack = {
        "schema_version": "1.0",
        "id": "local-inf2236-eval",
        "course_code": "INF2236",
        "title": "Programacion Avanzada en Java",
        "language": "es",
        "engine_type": "code_lab",
        "metadata": {
            "university_id": "local",
            "career_ids": ["cl-pucv-inf-2022"],
            "created_year": 2026,
            "updated_year": 2026,
            "version": "1.0.0",
            "authors": ["Test"],
            "license": "CC-BY-SA-4.0",
            "world_metaphor": "Fabrica Modular JVM",
        },
        "nodes": [
            {
                "id": "N1",
                "parent_ids": [],
                "branch": "theory",
                "block": "Bloque 1 · POO",
                "title": "Comparacion de Objetos y Polimorfismo",
                "summary": "Uso de equals() y @Override en Java",
                "story_script": (
                    "En Java, **equals()** compara contenido mientras `==` compara referencias. "
                    "Al sobrescribir con **@Override** se garantiza despacho dinamico."
                ),
                "eval_prompts": [
                    {
                        "id": "q1",
                        "question": "Explica la diferencia entre == y equals() en Java.",
                        "rubric_points": ["Diferencia referencia vs contenido", "Menciona NullPointerException"],
                        "challenge_type": "concept",
                        "language": "java",
                        "starter_code": None,
                    },
                    {
                        "id": "q2",
                        "question": "Corrige el bug de comparacion de Strings en el siguiente validador.",
                        "rubric_points": ["Reemplaza == por equals()", "Valida null de forma segura"],
                        "challenge_type": "debug",
                        "language": "java",
                        "starter_code": (
                            "public class Validador {\n"
                            "    public boolean esIgual(String a, String b) {\n"
                            "        return a == b;\n"
                            "    }\n"
                            "}"
                        ),
                    },
                ],
            }
        ],
    }
    inst = client.post("/api/v1/courses/install-pack", json=code_pack)
    assert inst.status_code == 200

    # 1. Con IA devolviendo prompt_reviews, code_fixes, corrected_solution y routing_suggestion
    def fake_complete_chat(_messages: list[dict[str, str]], **_kwargs: Any) -> AiCompletion:
        payload = {
            "score": 6.5,
            "covered_points": ["q1::0", "q1::1"],
            "imprecisions": ["En q2 mantuviste a == b sin usar equals() ni validar null."],
            "re_explanation": "Recuerda que en Java los Strings son objetos y deben compararse con equals().",
            "routing_suggestion": "Revisa la corrección línea por línea de la Pregunta 2 y reintenta este nodo.",
            "prompt_reviews": [
                {
                    "prompt_id": "q1",
                    "status": "passed",
                    "diagnosis": "Explicaste correctamente la diferencia entre referencia en memoria y contenido.",
                    "code_fixes": [],
                    "corrected_solution": None,
                },
                {
                    "prompt_id": "q2",
                    "status": "failed",
                    "diagnosis": "Dejaste la comparación por referencia == que falla con instancias distintas.",
                    "code_fixes": [
                        {
                            "broken_snippet": "return a == b;",
                            "fixed_snippet": "return a != null && a.equals(b);",
                            "why": "Este cambio permite comparar el valor de los Strings y evita un NullPointerException si a es null.",
                        }
                    ],
                    "corrected_solution": (
                        "```java\n"
                        "public class Validador {\n"
                        "    public boolean esIgual(String a, String b) {\n"
                        "        return a != null && a.equals(b);\n"
                        "    }\n"
                        "}\n"
                        "```"
                    ),
                },
            ],
        }
        return AiCompletion(text=json.dumps(payload), provider="groq", model="llama-3.3-70b-versatile")

    monkeypatch.setattr(ai_router, "complete_chat", fake_complete_chat)

    ev_res = client.post(
        "/api/v1/study/local-inf2236-eval/N1/evaluate",
        json={
            "answers": [
                {"prompt_id": "q1", "text": "== compara referencias en memoria y equals compara contenido evitando null"},
                {"prompt_id": "q2", "text": "public class Validador { public boolean esIgual(String a, String b) { return a == b; } }"},
            ],
            "cooldown_mode": "semester",
        },
    )
    assert ev_res.status_code == 200
    body = ev_res.json()
    assert body["score"] == 6.5
    assert body["routing_suggestion"] == "Revisa la corrección línea por línea de la Pregunta 2 y reintenta este nodo."
    assert len(body["prompt_reviews"]) == 2

    pr1, pr2 = body["prompt_reviews"]
    assert pr1["prompt_id"] == "q1"
    assert pr1["status"] == "passed"
    assert pr1["code_fixes"] == []
    assert pr1["corrected_solution"] is None

    assert pr2["prompt_id"] == "q2"
    assert pr2["status"] == "failed"
    assert len(pr2["code_fixes"]) == 1
    assert pr2["code_fixes"][0]["broken_snippet"] == "return a == b;"
    assert pr2["code_fixes"][0]["fixed_snippet"] == "return a != null && a.equals(b);"
    assert "Este cambio permite" in pr2["code_fixes"][0]["why"]
    # Los fences ```java ... ``` se limpian para renderizar el codigo directo en CodeMirror
    assert pr2["corrected_solution"] is not None
    assert "```" not in pr2["corrected_solution"]
    assert "a.equals(b)" in pr2["corrected_solution"]

    # 2. Fallback determinista limpio cuando el proveedor falla
    def fake_fail(*_args: Any, **_kwargs: Any) -> AiCompletion:
        raise ai_router.AiProviderError("Sin conexion")

    monkeypatch.setattr(ai_router, "complete_chat", fake_fail)

    fb_res = client.post(
        "/api/v1/study/local-inf2236-eval/N1/evaluate",
        json={
            "answers": [
                {"prompt_id": "q1", "text": "Diferencia referencia vs contenido y NullPointerException"},
                {"prompt_id": "q2", "text": "return a == b;"},
            ],
            "cooldown_mode": "semester",
        },
    )
    assert fb_res.status_code == 200
    fb_body = fb_res.json()
    assert fb_body["evaluated_by"] == "local_fallback"
    assert fb_body["routing_suggestion"]
    assert len(fb_body["prompt_reviews"]) == 2
    fb_q2 = next(r for r in fb_body["prompt_reviews"] if r["prompt_id"] == "q2")
    assert fb_q2["status"] in ("failed", "partial")
    assert len(fb_q2["code_fixes"]) >= 1
    assert fb_q2["corrected_solution"] is not None


def test_sanitize_code_prompt_strips_duplicate_code_and_formats_multiline_starter() -> None:
    from app.services.ai_router import sanitize_code_prompt
    from app.services.ingest import _normalize_prompt_item

    one_line_starter = (
        "public class Cuenta { private int saldo; public Cuenta(int saldo) { saldo = saldo; } "
        "public int getSaldo() { return saldo; } }"
    )
    duplicated_question = (
        f"[Debugging JAVA] Corrige el bug de sombreamiento de atributo en la siguiente clase: {one_line_starter}"
    )

    clean_q, clean_starter = sanitize_code_prompt(duplicated_question, one_line_starter, "java")

    assert clean_starter is not None
    assert "\n" in clean_starter
    assert clean_starter.count("\n") >= 4
    assert "    private int saldo;" in clean_starter
    assert "public class Cuenta" not in clean_q
    assert "getSaldo()" not in clean_q
    assert "Corrige el bug de sombreamiento" in clean_q

    # Tambien funciona cuando question trae el codigo en un bloque cercado ```java ... ```
    fenced_q = (
        "Identifica la salida exacta de este fragmento:\n"
        "```java\n"
        "public class Cuenta {\n    private int saldo;\n}\n"
        "```"
    )
    clean_q2, _ = sanitize_code_prompt(fenced_q, one_line_starter, "java")
    assert "```" not in clean_q2
    assert "private int saldo" not in clean_q2
    assert "Identifica la salida exacta" in clean_q2

    # _normalize_prompt_item aplica sanitize_code_prompt automaticamente
    norm = _normalize_prompt_item(
        {
            "id": "q1",
            "question": duplicated_question,
            "rubric_points": ["Usa this.saldo = saldo"],
            "challenge_type": "debug",
            "language": "java",
            "starter_code": one_line_starter,
        },
        p_idx=1,
        node_title="Constructores y this",
        nid="N1",
        engine_type="code_lab",
        default_language="java",
    )
    assert "public class Cuenta" not in norm["question"]
    assert norm["starter_code"].count("\n") >= 4


def test_strip_code_blocks_and_markdown_for_tts_and_code_lab_story_regeneration(
    client: TestClient,
) -> None:
    from app.services.tts import (
        split_story_sentences,
        strip_code_blocks_and_markdown_for_tts,
    )

    raw_story = (
        "En Java, el **polimorfismo dinámico** permite invocar métodos sobrescritos con **`@Override`** "
        "según el objeto real en el heap.\n\n"
        "```java\n"
        "class Animal {\n"
        "    public String sonido() {\n"
        "        return \"...\";\n"
        "    }\n"
        "}\n"
        "class Perro extends Animal {\n"
        "    @Override\n"
        "    public String sonido() {\n"
        "        return \"Guau\";\n"
        "    }\n"
        "}\n"
        "```\n\n"
        "Al usar **`super()`**, la subclase reutiliza la lógica base manteniendo el **encapsulamiento**."
    )

    cleaned = strip_code_blocks_and_markdown_for_tts(raw_story)
    assert "```" not in cleaned
    assert "**" not in cleaned
    assert "`" not in cleaned
    assert "class Animal" not in cleaned
    assert "return \"Guau\"" not in cleaned
    assert "polimorfismo dinámico" in cleaned
    assert "@Override" in cleaned
    assert "encapsulamiento" in cleaned

    sentences = split_story_sentences(raw_story)
    assert len(sentences) == 2
    assert all("class Animal" not in s and "**" not in s for s in sentences)

    # Regenerar historia en un ramo code_lab incluye **negrita** y bloque de codigo cercado con indentacion intacta
    java_notes = (
        b"# Herencia y Polimorfismo en Java\n"
        b"public class Base { public static void main(String[] args) { System.out.println(1); } }\n"
        b"Las subclases usan extends y @Override para especializar metodos.\n"
    )
    ing = client.post(
        "/api/v1/courses/ingest-local",
        data={
            "course_code": "INF2236",
            "title": "Programacion Orientada a Objetos",
            "engine_type": "code_lab",
        },
        files=[("files", ("herencia.md", java_notes, "text/markdown"))],
    )
    assert ing.status_code == 200
    cid = ing.json()["course_id"]

    regen = client.post(f"/api/v1/study/{cid}/N1/regenerate-story")
    assert regen.status_code == 200
    new_story = regen.json()["story_script"]
    assert "**" in new_story
    assert "```java" in new_story
    assert "    private final String" in new_story
