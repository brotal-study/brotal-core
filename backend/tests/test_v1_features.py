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


def test_detect_engine_type_identifies_language_studio_english_course() -> None:
    from app.services.ingest import ExtractedChunk, detect_engine_type

    eng_chunks = [
        ExtractedChunk(
            source_file="unit1_grammar.md",
            section_title="Unit 1: Present Simple & Verb to be",
            content=(
                "Grammar and vocabulary review: use Present Simple for daily routines and habits. "
                "Remember third person -s, do/does in questions, there is / there are and quantifiers "
                "(some, any, much, many). Includes listening and speaking practice."
            ),
        )
    ]

    assert detect_engine_type("ING9001", "Inglés 1 · Grammar & Vocabulary", eng_chunks) == (
        "language_studio",
        "en",
    )
    # También detecta por contenido de gramática/vocabulario aunque el código sea libre
    assert detect_engine_type("LIBRE01", "Preparation Workshop", eng_chunks) == (
        "language_studio",
        "en",
    )
    # No confunde un ramo técnico normal sin señales de idioma
    net_chunks = [
        ExtractedChunk(
            source_file="redes.md",
            section_title="Modelo OSI",
            content="Las tramas Ethernet operan en la capa de enlace mediante direcciones MAC.",
        )
    ]
    assert detect_engine_type("INF2324", "Redes de Computadores", net_chunks) == (
        "concept_tree",
        "text",
    )


def test_language_studio_local_ingest_and_bilingual_evaluation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ai_router

    english_notes = (
        b"# Unit 1: Present Simple and Daily Routines\n"
        b"Grammar focus: Verb to be (am/is/are) and Present Simple affirmative, negative (don't/doesn't) "
        b"and interrogative (do/does). Third person singular adds -s/-es.\n\n"
        b"# Unit 2: There is / There are and Quantifiers\n"
        b"Vocabulary: classroom objects and study habits. Use some in affirmative sentences and any in "
        b"negative sentences and questions with countable and uncountable nouns.\n"
    )

    ing = client.post(
        "/api/v1/courses/ingest-local",
        data={
            "course_code": "ING9001",
            "title": "Inglés 1",
            "engine_type": "language_studio",
        },
        files=[("files", ("ing9001_units.md", english_notes, "text/markdown"))],
    )
    assert ing.status_code == 200
    ing_data = ing.json()
    assert ing_data["engine_type"] == "language_studio"
    assert ing_data["detected_language"] == "en"
    cid = ing_data["course_id"]

    tree_res = client.get(f"/api/v1/courses/{cid}/tree")
    assert tree_res.status_code == 200
    tree = tree_res.json()
    assert tree["engine_type"] == "language_studio"
    assert len(tree["nodes"]) >= 6

    first_node = tree["nodes"][0]
    assert "**" in first_node["story_script"]
    assert "```en" in first_node["story_script"]
    challenge_types = {p["challenge_type"] for p in first_node["eval_prompts"]}
    assert {"fill_blank", "translate", "speaking_prompt"}.issubset(challenge_types)
    assert all(p["language"] == "en" for p in first_node["eval_prompts"])

    captured_system_prompts: list[str] = []

    def fake_complete_chat(messages: list[dict[str, str]], **_kwargs: Any) -> AiCompletion:
        captured_system_prompts.append(messages[0]["content"])
        prompts = first_node["eval_prompts"]
        payload = {
            "score": 7.8,
            "covered_points": [f"{prompts[0]['id']}::0", f"{prompts[1]['id']}::0", f"{prompts[2]['id']}::0"],
            "imprecisions": ["En la segunda respuesta faltó agregar -s en tercera persona singular ('studies')."],
            "re_explanation": "",
            "routing_suggestion": "Buen dominio comunicativo; repasa la -s de tercera persona antes de avanzar.",
            "prompt_reviews": [
                {
                    "prompt_id": prompts[0]["id"],
                    "status": "passed",
                    "diagnosis": "Completaste correctamente el cuantificador y el verbo.",
                    "code_fixes": [],
                    "corrected_solution": None,
                },
                {
                    "prompt_id": prompts[1]["id"],
                    "status": "partial",
                    "diagnosis": "Estructura clara, pero omitiste la conjugación de tercera persona singular.",
                    "code_fixes": [
                        {
                            "broken_snippet": "She study in the library every morning.",
                            "fixed_snippet": "She studies in the library every morning.",
                            "why": "Este cambio corrige la conjugación en Present Simple para tercera persona singular (she).",
                        }
                    ],
                    "corrected_solution": "She studies in the library every morning and reviews her vocabulary notes.",
                },
                {
                    "prompt_id": prompts[2]["id"],
                    "status": "passed",
                    "diagnosis": "Respuesta fluida en inglés con vocabulario pertinente a tu rutina.",
                    "code_fixes": [],
                    "corrected_solution": None,
                },
            ],
        }
        return AiCompletion(text=json.dumps(payload), provider="groq", model="llama-3.3-70b-versatile")

    monkeypatch.setattr(ai_router, "complete_chat", fake_complete_chat)

    ev = client.post(
        f"/api/v1/study/{cid}/{first_node['id']}/evaluate",
        json={
            "answers": [
                {"prompt_id": first_node["eval_prompts"][0]["id"], "text": "Is there any coffee on the table?"},
                {"prompt_id": first_node["eval_prompts"][1]["id"], "text": "She study in the library every morning."},
                {
                    "prompt_id": first_node["eval_prompts"][2]["id"],
                    "text": "I wake up at seven every day. I attend classes in the morning and study English in the afternoon.",
                },
            ],
            "cooldown_mode": "semester",
        },
    )
    assert ev.status_code == 200
    ev_body = ev.json()
    assert ev_body["passed"] is True
    assert ev_body["score"] == 7.8
    assert any("language_studio" in sp for sp in captured_system_prompts)
    assert len(ev_body["prompt_reviews"]) == len(first_node["eval_prompts"])
    pr_translate = ev_body["prompt_reviews"][1]
    assert pr_translate["status"] == "partial"
    assert pr_translate["code_fixes"][0]["fixed_snippet"] == "She studies in the library every morning."
    assert "Este cambio corrige" in pr_translate["code_fixes"][0]["why"]
    assert "She studies" in (pr_translate["corrected_solution"] or "")


def test_phrase_tts_endpoint_validation_and_english_mp3_cache(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import tts

    # 1. Rechaza texto vacio o solo espacios y texto > 1200 caracteres
    r_empty = client.post(
        "/api/v1/study/local-ing9001/tts-phrase",
        json={"text": "", "lang": "en", "accent": "us"},
    )
    assert r_empty.status_code == 422

    r_spaces = client.post(
        "/api/v1/study/local-ing9001/tts-phrase",
        json={"text": "    ", "lang": "en", "accent": "us"},
    )
    assert r_spaces.status_code == 422

    r_too_long = client.post(
        "/api/v1/study/local-ing9001/tts-phrase",
        json={"text": "a" * 1201, "lang": "en", "accent": "us"},
    )
    assert r_too_long.status_code == 422

    # 2. Sintetiza con voz neural en ingles y cachea por SHA-256
    calls: list[tuple[str, str]] = []

    async def fake_run_edge_tts(text: str, voice: str, out_path: Path) -> dict[str, Any]:
        calls.append((text, voice))
        out_path.write_bytes(b"ID3-FAKE-ENGLISH-MP3-BYTES")
        return {"sentences": [], "words": []}

    monkeypatch.setattr(tts, "_run_edge_tts", fake_run_edge_tts)

    phrase = "Complete with there is / there are: ___ ___ any coffee on the table?"
    ok_us = client.post(
        "/api/v1/study/local-ing9001/tts-phrase",
        json={"text": phrase, "lang": "en", "accent": "us"},
    )
    assert ok_us.status_code == 200
    assert ok_us.headers["content-type"].startswith("audio/mpeg")
    assert ok_us.content == b"ID3-FAKE-ENGLISH-MP3-BYTES"
    assert len(calls) == 1
    assert calls[0][1] == "en-US-AriaNeural"
    assert "blank" in calls[0][0]

    # Segunda llamada identica usa el MP3 cacheado sin invocar edge-tts de nuevo
    ok_us_cached = client.post(
        "/api/v1/study/local-ing9001/tts-phrase",
        json={"text": phrase, "lang": "en", "accent": "us"},
    )
    assert ok_us_cached.status_code == 200
    assert len(calls) == 1

    # Acento britanico selecciona en-GB-SoniaNeural
    ok_gb = client.post(
        "/api/v1/study/local-ing9001/tts-phrase",
        json={"text": "What is your daily routine?", "lang": "en", "accent": "gb"},
    )
    assert ok_gb.status_code == 200
    assert ok_gb.headers["content-type"].startswith("audio/mpeg")
    assert calls[-1][1] == "en-GB-SoniaNeural"


# ---------------- v1.2.2: Animaciones explicativas auto-adaptativas (node_storyboards) ----------------

_STORYBOARD_COURSE = "local-inf2236-anim"


def _storyboard_node(node_id: str, title: str, summary: str, story: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "parent_ids": [],
        "branch": "theory",
        "block": "Bloque 1 · Animaciones",
        "title": title,
        "summary": summary,
        "story_script": story,
        "eval_prompts": [
            {
                "id": "q1",
                "question": f"Explica {title}.",
                "rubric_points": ["Punto clave"],
                "challenge_type": "concept",
                "language": "java",
                "starter_code": None,
            }
        ],
    }


def _install_storyboard_pack(client: TestClient) -> None:
    pack = {
        "schema_version": "1.0",
        "id": _STORYBOARD_COURSE,
        "course_code": "INF2236",
        "title": "Programacion Avanzada en Java y SQL",
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
            _storyboard_node(
                "OOP",
                "Herencia, Polimorfismo y @Override",
                "Despacho dinamico con extends y super()",
                "La clase Perro extends Animal y aplica @Override sobre hablar(). "
                "Con polimorfismo, la JVM resuelve el tipo dinamico en el heap. "
                "Con super.hablar() se invoca la version de la superclase.",
            ),
            _storyboard_node(
                "ERR",
                "Excepciones con try / catch",
                "NullPointerException y stack unwinding",
                "Cuando un objeto es null, invocar un metodo lanza NullPointerException. "
                "La excepcion recorre la pila hasta encontrar un bloque try / catch. "
                "Corregir el bug implica validar antes de usar la referencia.",
            ),
            _storyboard_node(
                "SQL",
                "Consultas con SELECT y GROUP BY",
                "Orden logico FROM, WHERE, GROUP BY, HAVING y SELECT",
                "La consulta SELECT carrera, COUNT(*) FROM alumnos WHERE edad > 20 "
                "GROUP BY carrera HAVING COUNT(*) > 1 se evalua primero por FROM. "
                "Luego WHERE filtra filas y GROUP BY agrupa antes de proyectar.",
            ),
            _storyboard_node(
                "DS",
                "ArrayList y HashMap",
                "Capacidad, size y buckets",
                "Un ArrayList guarda elementos en un arreglo interno con capacidad. "
                "Un HashMap ubica cada clave en buckets usando hash(k) % N.",
            ),
        ],
    }
    res = client.post("/api/v1/courses/install-pack", json=pack)
    assert res.status_code == 200, res.text


def _assert_storyboard_contract(body: dict[str, Any]) -> None:
    assert 6 <= len(body["source_code"].splitlines()) <= 22
    assert 2 <= len(body["subgoals"]) <= 4
    assert 5 <= len(body["steps"]) <= 9
    subgoal_ids = {g["id"] for g in body["subgoals"]}
    assert all(s["subgoal_id"] in subgoal_ids for s in body["steps"])
    assert all(len(s["caption"].split()) <= 12 for s in body["steps"])
    assert any((s.get("checkpoint") or {}).get("enabled") for s in body["steps"])
    assert [s["index"] for s in body["steps"]] == list(range(len(body["steps"])))


def test_storyboard_404_then_autodetects_and_persists_variants(client: TestClient) -> None:
    _install_storyboard_pack(client)
    base = f"/api/v1/study/{_STORYBOARD_COURSE}"

    assert client.get(f"{base}/OOP/storyboard").status_code == 404
    assert client.get(f"{base}/NOPE/storyboard").status_code == 404
    assert client.post(f"{base}/NOPE/storyboard").status_code == 404

    expected = {
        "OOP": ("oop_dispatch", {"classes", "references", "heap_objects", "dispatch"}),
        "ERR": ("error_contrast", {"phase", "code_view", "exception", "call_stack"}),
        "SQL": ("sql_pipeline", {"active_clause", "pipeline_stages", "clause_sql", "columns", "rows", "note"}),
        "DS": ("data_structure", {"structure_type", "size", "capacity", "cells", "pointers", "buckets"}),
    }
    for node_id, (variant, state_keys) in expected.items():
        res = client.post(f"{base}/{node_id}/storyboard")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["variant"] == variant, (node_id, body["variant"])
        assert body["provider"] == "local_fallback"
        _assert_storyboard_contract(body)
        assert state_keys <= set(body["steps"][0]["state"].keys())
        if variant == "error_contrast":
            assert body["fixed_code"]
            assert "contrast" not in body["steps"][0]["state"]
            assert "contrast" in body["steps"][-1]["state"]
        if variant == "sql_pipeline":
            assert body["language"] == "sql"

        fetched = client.get(f"{base}/{node_id}/storyboard")
        assert fetched.status_code == 200
        assert fetched.json() == body

    # La columna legada storyboard_json / PackNode.storyboard_ref no se toca
    tree = client.get(f"/api/v1/courses/{_STORYBOARD_COURSE}/tree").json()
    assert all(n["storyboard_ref"] is None for n in tree["nodes"])


def test_storyboard_cache_vs_force_and_llm_sanitization(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ai_router

    _install_storyboard_pack(client)
    base = f"/api/v1/study/{_STORYBOARD_COURSE}/OOP/storyboard"
    first = client.post(base)
    assert first.status_code == 200
    assert first.json()["provider"] == "local_fallback"

    calls: list[int] = []

    def fake_complete_chat(_messages: list[dict[str, str]], **_kwargs: Any) -> AiCompletion:
        calls.append(1)
        payload = {
            "variant": "oop_dispatch",
            "language": "java",
            "title": "Despacho de hablar()",
            "source_code": (
                "class Animal {\n"
                '  void hablar() { System.out.println("..."); }\n'
                "}\n"
                "class Perro extends Animal {\n"
                '  @Override void hablar() { System.out.println("Guau"); }\n'
                "}\n"
                "Animal a = new Perro();\n"
                "a.hablar();"
            ),
            "fixed_code": None,
            "subgoals": [{"id": "s1", "label": "Jerarquia"}, {"id": "s2", "label": "Despacho"}],
            "steps": [
                {
                    "index": i,
                    "subgoal_id": "s1" if i < 3 else "s2",
                    "active_lines": [min(8, i + 1)],
                    "caption": (
                        "Este caption es deliberadamente demasiado largo y debe quedar recortado "
                        "a doce palabras como maximo por el sanitizador"
                        if i == 0
                        else f"Paso {i} del despacho dinamico"
                    ),
                    "checkpoint": {
                        "enabled": i == 3,
                        "question": "Que metodo se ejecuta?",
                        "options": ["Animal.hablar", "Perro.hablar"],
                        "correct_index": 1,
                        "explanation": "El tipo dinamico manda.",
                    },
                    "state": {
                        "classes": [{"name": "Animal", "parent": None, "methods": ["hablar()"], "active": False}],
                        "references": [
                            {"var_name": "a", "static_type": "Animal", "dynamic_type": "Perro", "heap_id": "o1"}
                        ],
                        "heap_objects": [{"id": "o1", "class_name": "Perro", "fields": []}],
                        "dispatch": {
                            "call_expr": "a.hablar()",
                            "static_check": "Animal declara hablar()",
                            "lookup_path": ["Perro", "Animal"],
                            "resolved_class": "Perro",
                            "resolved_method": "Perro.hablar()",
                            "via_super": False,
                        },
                    },
                }
                for i in range(6)
            ],
        }
        return AiCompletion(text=json.dumps(payload), provider="groq", model="llama-3.3-70b-versatile")

    monkeypatch.setattr(ai_router, "complete_chat", fake_complete_chat)

    cached = client.post(base)
    assert cached.status_code == 200
    assert cached.json() == first.json()
    assert calls == []

    forced = client.post(f"{base}?force=true")
    assert forced.status_code == 200
    body = forced.json()
    assert calls == [1]
    assert body["provider"] == "groq"
    assert body["variant"] == "oop_dispatch"
    _assert_storyboard_contract(body)
    assert client.get(base).json()["provider"] == "groq"


def _parse_sse(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def test_storyboard_stream_emits_weighted_progress_until_100(client: TestClient) -> None:
    _install_storyboard_pack(client)
    url = f"/api/v1/study/{_STORYBOARD_COURSE}/SQL/storyboard/stream"

    assert client.get(f"/api/v1/study/{_STORYBOARD_COURSE}/NOPE/storyboard/stream").status_code == 404

    res = client.get(url)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(res.text)
    assert [e["stage"] for e in events] == ["analyzing", "generating", "validating", "done"]
    assert [e["pct"] for e in events] == [18, 52, 86, 100]
    done = events[-1]["storyboard"]
    assert done["variant"] == "sql_pipeline"
    _assert_storyboard_contract(done)

    # Persistido en SQLite por la conexion dedicada del stream
    stored = client.get(f"/api/v1/study/{_STORYBOARD_COURSE}/SQL/storyboard")
    assert stored.status_code == 200
    assert stored.json()["updated_at"] == done["updated_at"]

    # Segunda llamada sin force usa cache (sin etapa generating)
    cached_events = _parse_sse(client.get(url).text)
    assert [e["pct"] for e in cached_events] == [18, 86, 100]
    assert cached_events[-1]["storyboard"]["updated_at"] == done["updated_at"]

    forced_events = _parse_sse(client.get(f"{url}?force=true").text)
    assert [e["pct"] for e in forced_events] == [18, 52, 86, 100]


def test_storyboard_stream_reports_clean_error_event(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import study as study_router

    _install_storyboard_pack(client)

    def broken_generator(**_kwargs: Any) -> tuple[dict[str, Any], str]:
        raise RuntimeError("motor caido")

    monkeypatch.setattr(study_router, "generate_code_storyboard_with_ai", broken_generator)
    res = client.get(f"/api/v1/study/{_STORYBOARD_COURSE}/OOP/storyboard/stream")
    assert res.status_code == 200
    events = _parse_sse(res.text)
    assert events[-1]["stage"] == "error"
    assert "motor caido" in events[-1]["detail"]
    assert client.get(f"/api/v1/study/{_STORYBOARD_COURSE}/OOP/storyboard").status_code == 404


def test_regenerate_story_preserves_canonical_node_storyboard(client: TestClient) -> None:
    _install_storyboard_pack(client)
    base = f"/api/v1/study/{_STORYBOARD_COURSE}"
    created = client.post(f"{base}/ERR/storyboard")
    assert created.status_code == 200
    assert client.post(f"{base}/OOP/storyboard").status_code == 200

    # Cambiar el estilo de explicacion ("Otra explicacion") conserva la escena canonica del nodo;
    # solo se regenera cuando el usuario solicita ?force=true explicitamente.
    regen = client.post(f"{base}/ERR/regenerate-story")
    assert regen.status_code == 200

    preserved = client.get(f"{base}/ERR/storyboard")
    assert preserved.status_code == 200
    assert preserved.json()["updated_at"] == created.json()["updated_at"]
    assert client.get(f"{base}/OOP/storyboard").status_code == 200
    tree = client.get(f"/api/v1/courses/{_STORYBOARD_COURSE}/tree")
    assert tree.status_code == 200
    assert all(n["storyboard_ref"] is None for n in tree.json()["nodes"])


# ---------------- v1.2.3: Language Studio interactivo + Language Chat ----------------


def test_eval_prompt_validates_four_new_language_challenge_types_and_retrocompat() -> None:
    from app.schemas.pack import EvalPrompt

    # Retrocompatibilidad estricta: EvalPrompt sin interaction_data sigue valido
    legacy = EvalPrompt.model_validate(
        {
            "id": "q_legacy",
            "question": "Complete with is/are.",
            "rubric_points": ["Usa concordancia correcta"],
            "challenge_type": "fill_blank",
            "language": "en",
        }
    )
    assert legacy.interaction_data is None
    assert legacy.challenge_type == "fill_blank"

    for ct, payload in (
        ("word_order", {"tiles": ["She", "goes", "to", "school"], "distractors": ["go"], "hint_es": "3a persona"}),
        ("categorize", {"categories": ["Countable", "Uncountable"], "items": ["two books", "some coffee", "many pens", "much time"]}),
        ("find_error", {"sentence": "She don't study on Mondays.", "tokens": ["She", "don't", "study", "on", "Mondays."], "allow_no_error": True}),
        ("dictation", {"audio_text": "She studies English every day.", "accent": "us", "hint_es": "Escucha y escribe."}),
    ):
        ep = EvalPrompt.model_validate(
            {
                "id": f"q_{ct}",
                "question": f"Task {ct}",
                "rubric_points": ["Criterio verificable"],
                "challenge_type": ct,
                "language": "en",
                "interaction_data": payload,
            }
        )
        assert ep.challenge_type == ct
        assert ep.language == "en"
        assert ep.interaction_data == payload
        dumped = ep.model_dump()
        assert dumped["interaction_data"] == payload


def test_defensive_normalizer_guarantees_valid_interaction_data_for_empty_payloads() -> None:
    from app.services.ai_router import normalize_language_interaction_data
    from app.services.ingest import _normalize_eval_prompt

    # 1. word_order con None / {} / incompleto
    for bad in (None, {}, {"tiles": ["only", "two"], "distractors": []}):
        wo = normalize_language_interaction_data("word_order", bad, node_title="Present Simple")
        assert wo is not None
        assert len(wo["tiles"]) >= 4
        assert 1 <= len(wo["distractors"]) <= 2
        assert isinstance(wo["hint_es"], str) and wo["hint_es"].strip()

    # 2. categorize con None / {} / incompleto
    for bad in (None, {}, {"categories": ["OnlyOne"], "items": ["a"]}):
        cat = normalize_language_interaction_data("categorize", bad, node_title="Quantifiers")
        assert cat is not None
        assert len(cat["categories"]) >= 2
        assert len(cat["items"]) >= 4
        assert isinstance(cat.get("expected_map"), dict)

    # 3. find_error con None / {} / solo sentence sin tokens
    for bad in (None, {}, {"sentence": "There is many chairs in this room."}):
        fe = normalize_language_interaction_data("find_error", bad, node_title="There is / There are")
        assert fe is not None
        assert isinstance(fe["sentence"], str) and len(fe["sentence"].split()) >= 4
        assert len(fe["tokens"]) >= 4
        assert isinstance(fe["allow_no_error"], bool)

    # 4. dictation con None / {} / audio vacio
    for bad in (None, {}, {"audio_text": "", "accent": "invalid"}):
        di = normalize_language_interaction_data("dictation", bad, node_title="Listening")
        assert di is not None
        assert isinstance(di["audio_text"], str) and len(di["audio_text"].strip()) >= 4
        assert di["accent"] in ("us", "gb", "au")
        assert isinstance(di["hint_es"], str) and di["hint_es"].strip()

    # _normalize_eval_prompt preserva y repara interaction_data en ingesta
    repaired = _normalize_eval_prompt(
        {
            "id": "q1",
            "question": "Ordena la oración.",
            "rubric_points": ["Orden natural"],
            "challenge_type": "word_order",
            "interaction_data": {},
        },
        p_idx=1,
        node_title="Present Simple",
        nid="N1",
        engine_type="language_studio",
        default_language="en",
    )
    assert repaired["language"] == "en"
    assert repaired["starter_code"] is None
    assert len(repaired["interaction_data"]["tiles"]) >= 4
    assert 1 <= len(repaired["interaction_data"]["distractors"]) <= 2


def test_language_studio_interactive_evaluation_offline_and_with_ai(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ai_router

    interactive_pack = {
        "schema_version": "1.0",
        "id": "local-ing9002-interactive",
        "course_code": "ING9002",
        "title": "Inglés 1 · Interactive Studio",
        "language": "es",
        "engine_type": "language_studio",
        "metadata": {
            "university_id": "local",
            "career_ids": ["cl-pucv-inf-2022"],
            "created_year": 2026,
            "updated_year": 2026,
            "version": "1.0.0",
            "authors": ["Test"],
            "license": "CC-BY-SA-4.0",
            "world_metaphor": "Campus Bilingue",
        },
        "nodes": [
            {
                "id": "L1",
                "parent_ids": [],
                "branch": "theory",
                "block": "Bloque 1 · Present Simple",
                "title": "Present Simple & Quantifiers",
                "summary": "Rutinas, tercera persona singular, countable/uncountable y dictado.",
                "story_script": (
                    "En inglés respetamos **Sujeto + Verbo + Complemento** y **doesn't + verbo base**.\n\n"
                    "```en\nShe goes to school every day.\n```\n"
                ),
                "eval_prompts": [
                    {
                        "id": "q1",
                        "question": "Ordena los bloques en inglés y descarta distractores.",
                        "rubric_points": ["Ordena correctamente la oración en 3a persona", "Descarta distractores"],
                        "challenge_type": "word_order",
                        "language": "en",
                        "starter_code": None,
                        "interaction_data": {
                            "tiles": ["She", "goes", "to", "school", "every", "day"],
                            "distractors": ["go", "does"],
                            "hint_es": "3a persona singular afirmativa",
                        },
                    },
                    {
                        "id": "q2",
                        "question": "Clasifica cada expresión en Countable o Uncountable.",
                        "rubric_points": ["Distingue sustantivos contables e incontables"],
                        "challenge_type": "categorize",
                        "language": "en",
                        "starter_code": None,
                        "interaction_data": {
                            "categories": ["Countable", "Uncountable"],
                            "items": ["two notebooks", "many students", "some coffee", "much homework"],
                            "expected_map": {
                                "two notebooks": "Countable",
                                "many students": "Countable",
                                "some coffee": "Uncountable",
                                "much homework": "Uncountable",
                            },
                        },
                    },
                    {
                        "id": "q3",
                        "question": "Detecta y corrige el error en la oración.",
                        "rubric_points": ["Corrige el auxiliar de 3a persona singular"],
                        "challenge_type": "find_error",
                        "language": "en",
                        "starter_code": None,
                        "interaction_data": {
                            "sentence": "She don't study English on Mondays.",
                            "tokens": ["She", "don't", "study", "English", "on", "Mondays."],
                            "allow_no_error": True,
                            "error_token": "don't",
                            "correction": "doesn't",
                        },
                    },
                    {
                        "id": "q4",
                        "question": "Escucha el audio y transcribe la frase en inglés.",
                        "rubric_points": ["Transcribe correctamente todas las palabras del dictado"],
                        "challenge_type": "dictation",
                        "language": "en",
                        "starter_code": None,
                        "interaction_data": {
                            "audio_text": "There aren't any chairs left in the classroom.",
                            "accent": "us",
                            "hint_es": "Atención a la contracción negativa y el plural.",
                        },
                    },
                ],
            }
        ],
    }
    inst = client.post("/api/v1/courses/install-pack", json=interactive_pack)
    assert inst.status_code == 200, inst.text

    # Verificar que GET /tree preserva interaction_data de los 4 tipos
    tree = client.get("/api/v1/courses/local-ing9002-interactive/tree").json()
    prompts = tree["nodes"][0]["eval_prompts"]
    assert [p["challenge_type"] for p in prompts] == ["word_order", "categorize", "find_error", "dictation"]
    assert all(isinstance(p["interaction_data"], dict) for p in prompts)

    # 1. Evaluación offline (sin API key) con respuestas correctas -> 10/10 aprobado
    ev_perfect = client.post(
        "/api/v1/study/local-ing9002-interactive/L1/evaluate",
        json={
            "answers": [
                {"prompt_id": "q1", "text": "She goes to school every day"},
                {"prompt_id": "q2", "text": "Countable: two notebooks, many students\nUncountable: some coffee, much homework"},
                {"prompt_id": "q3", "text": "Error: don't -> Corrección: doesn't"},
                {"prompt_id": "q4", "text": "There aren't any chairs left in the classroom."},
            ],
            "cooldown_mode": "semester",
        },
    )
    assert ev_perfect.status_code == 200, ev_perfect.text
    perf = ev_perfect.json()
    assert perf["evaluated_by"] == "local_fallback"
    assert perf["passed"] is True
    assert perf["score"] == 10.0
    assert all(r["status"] == "passed" for r in perf["prompt_reviews"])

    # 2. Evaluación offline con errores reales -> devuelve diagnósticos, code_fixes y audio_text en dictation
    ev_err = client.post(
        "/api/v1/study/local-ing9002-interactive/L1/evaluate",
        json={
            "answers": [
                {"prompt_id": "q1", "text": "She go to school every day"},
                {"prompt_id": "q2", "text": "Countable: two notebooks, some coffee\nUncountable: many students, much homework"},
                {"prompt_id": "q3", "text": "Sin error"},
                {"prompt_id": "q4", "text": "There is chairs in classroom"},
            ],
            "cooldown_mode": "semester",
        },
    )
    assert ev_err.status_code == 200, ev_err.text
    err_body = ev_err.json()
    assert err_body["evaluated_by"] == "local_fallback"
    assert err_body["score"] < 7.0
    assert err_body["passed"] is False
    reviews_by_id = {r["prompt_id"]: r for r in err_body["prompt_reviews"]}
    assert reviews_by_id["q1"]["status"] in ("partial", "failed")
    assert len(reviews_by_id["q1"]["code_fixes"]) >= 1
    assert "She goes to school every day" in (reviews_by_id["q1"]["corrected_solution"] or "")
    assert reviews_by_id["q2"]["status"] == "partial"
    assert len(reviews_by_id["q2"]["code_fixes"]) >= 1
    assert reviews_by_id["q3"]["status"] == "failed"
    assert "doesn't" in (reviews_by_id["q3"]["corrected_solution"] or "")
    assert reviews_by_id["q4"]["status"] in ("partial", "failed")
    assert "There aren't any chairs left in the classroom." in (reviews_by_id["q4"]["corrected_solution"] or "")

    # 3. Evaluación con IA mockeada recibe interaction_data en el payload del evaluador
    captured_user_payloads: list[dict[str, Any]] = []

    def fake_complete_chat(messages: list[dict[str, str]], **_kwargs: Any) -> AiCompletion:
        captured_user_payloads.append(json.loads(messages[1]["content"]))
        payload = {
            "score": 8.0,
            "covered_points": ["q1::0", "q1::1", "q2::0", "q3::0"],
            "imprecisions": ["En el dictado faltó la contracción aren't."],
            "re_explanation": "",
            "routing_suggestion": "Aprobaste; repasa la transcripción del dictado antes de avanzar.",
            "prompt_reviews": [
                {"prompt_id": "q1", "status": "passed", "diagnosis": "Orden correcto.", "code_fixes": [], "corrected_solution": None},
                {"prompt_id": "q2", "status": "passed", "diagnosis": "Categorías correctas.", "code_fixes": [], "corrected_solution": None},
                {"prompt_id": "q3", "status": "passed", "diagnosis": "Error detectado y corregido.", "code_fixes": [], "corrected_solution": None},
                {
                    "prompt_id": "q4",
                    "status": "partial",
                    "diagnosis": "Faltó la contracción negativa aren't.",
                    "code_fixes": [
                        {
                            "broken_snippet": "There are not chairs left in the classroom.",
                            "fixed_snippet": "There aren't any chairs left in the classroom.",
                            "why": "Este cambio corrige la contracción y el cuantificador any escuchados en el audio.",
                        }
                    ],
                    "corrected_solution": "There aren't any chairs left in the classroom.",
                },
            ],
        }
        return AiCompletion(text=json.dumps(payload), provider="groq", model="llama-3.3-70b-versatile")

    monkeypatch.setattr(ai_router, "complete_chat", fake_complete_chat)
    ev_ai = client.post(
        "/api/v1/study/local-ing9002-interactive/L1/evaluate",
        json={
            "answers": [
                {"prompt_id": "q1", "text": "She goes to school every day"},
                {"prompt_id": "q2", "text": "Countable: two notebooks, many students\nUncountable: some coffee, much homework"},
                {"prompt_id": "q3", "text": "Error: don't -> Corrección: doesn't"},
                {"prompt_id": "q4", "text": "There are not chairs left in the classroom."},
            ],
            "cooldown_mode": "semester",
        },
    )
    assert ev_ai.status_code == 200
    assert ev_ai.json()["evaluated_by"] == "groq"
    eval_items = captured_user_payloads[0]["evaluation_items"]
    assert eval_items[0]["interaction_data"]["tiles"] == ["She", "goes", "to", "school", "every", "day"]
    assert eval_items[3]["interaction_data"]["audio_text"] == "There aren't any chairs left in the classroom."


def test_language_practice_chat_full_flow_start_turn_finish_and_404(client: TestClient) -> None:
    english_notes = (
        b"# Unit 1: Present Simple and Daily Routines\n"
        b"Grammar focus: Present Simple affirmative, negative (don't/doesn't) and questions (do/does).\n\n"
        b"# Unit 2: There is / There are and Quantifiers\n"
        b"Countable and uncountable nouns with some, any, much and many.\n"
    )
    ing = client.post(
        "/api/v1/courses/ingest-local",
        data={"course_code": "ING9010", "title": "Inglés 1 · Chat Studio", "engine_type": "language_studio"},
        files=[("files", ("ing9010.md", english_notes, "text/markdown"))],
    )
    assert ing.status_code == 200
    cid = ing.json()["course_id"]

    tree = client.get(f"/api/v1/courses/{cid}/tree").json()
    node_id = tree["nodes"][0]["id"]
    # El árbol completo language_studio mezcla los 4 tipos interactivos además de los clásicos
    all_cts = {p["challenge_type"] for n in tree["nodes"] for p in n["eval_prompts"]}
    assert {"word_order", "categorize", "find_error", "dictation"}.issubset(all_cts)

    # 404 si el curso o nodo no existe
    assert client.post("/api/v1/study/no-such-course/N1/language-chat", json={"start": True}).status_code == 404
    assert client.post(f"/api/v1/study/{cid}/NOPE/language-chat", json={"start": True}).status_code == 404

    # 1. Start=True -> 3 misiones, saludo <= 25 palabras, chips y sentence_starter
    r_start = client.post(
        f"/api/v1/study/{cid}/{node_id}/language-chat",
        json={"start": True},
    )
    assert r_start.status_code == 200, r_start.text
    start_data = r_start.json()
    assert len(start_data["missions"]) == 3
    assert start_data["missions_completed"] == []
    assert len(start_data["reply_en"].split()) <= 25
    assert start_data["translation_es"].strip()
    assert 4 <= len(start_data["lexical_chips"]) <= 6
    assert start_data["sentence_starter"]
    assert start_data["session_summary"] is None

    # 2. Turno intermedio con error típico L1-español -> Salient Recast en **negrita** + inline_correction_es + avance misión
    history = [{"role": "assistant", "content": start_data["reply_en"]}]
    user_turn_1 = "She don't study English in the morning."
    r_turn1 = client.post(
        f"/api/v1/study/{cid}/{node_id}/language-chat",
        json={
            "message": user_turn_1,
            "history": history,
            "missions": start_data["missions"],
            "turn_index": 1,
            "start": False,
            "finish": False,
        },
    )
    assert r_turn1.status_code == 200, r_turn1.text
    t1 = r_turn1.json()
    assert len(t1["reply_en"].split()) <= 25
    assert "**" in t1["reply_en"]
    assert "doesn't" in t1["reply_en"].lower()
    assert t1["inline_correction_es"] is not None
    assert 0 in t1["missions_completed"]
    assert len(t1["missions"]) == 3

    # 3. Finish=True -> cierre + session_summary con pares {said, better, why}
    history.extend(
        [
            {"role": "user", "content": user_turn_1},
            {"role": "assistant", "content": t1["reply_en"]},
            {"role": "user", "content": "Do you study English every morning?"},
        ]
    )
    r_finish = client.post(
        f"/api/v1/study/{cid}/{node_id}/language-chat",
        json={
            "message": "",
            "history": history,
            "missions": start_data["missions"],
            "turn_index": 2,
            "start": False,
            "finish": True,
        },
    )
    assert r_finish.status_code == 200, r_finish.text
    fin = r_finish.json()
    assert fin["reply_en"].strip()
    assert fin["translation_es"].strip()
    summary = fin["session_summary"]
    assert isinstance(summary, dict)
    assert summary["headline"].strip()
    assert 2 <= len(summary["items"]) <= 3
    for item in summary["items"]:
        assert {"said", "better", "why"} <= set(item.keys())
        assert item["said"].strip() and item["better"].strip() and item["why"].strip()
    assert any("doesn't" in it["better"].lower() for it in summary["items"])


# ---------------- v1.2.4: Fix error_contrast + Mini-Video Modo Cine (node_cinema_reels) ----------------


def test_error_contrast_sanitizer_never_injects_npe_fallback_and_hides_contrast_in_buggy_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ai_router

    _install_storyboard_pack(client)
    calc_source = (
        "public class Calculadora {\n"
        "    static int dividir(int a, int b) {\n"
        "        return a / b;\n"
        "    }\n"
        "    public static void main(String[] args) {\n"
        "        System.out.println(dividir(10, 0));\n"
        "    }\n"
        "}"
    )
    calc_fixed = (
        "public class Calculadora {\n"
        "    static int dividir(int a, int b) {\n"
        "        if (b == 0) throw new IllegalArgumentException(\"Divisor cero\");\n"
        "        return a / b;\n"
        "    }\n"
        "    public static void main(String[] args) {\n"
        "        System.out.println(dividir(10, 2));\n"
        "    }\n"
        "}"
    )

    # Caso 1: IA genera codigo propio (Calculadora.dividir / ArithmeticException), mete contrast indebido
    # en buggy_run y omite contrast en fixed_diff.
    def fake_calc_with_fix(_messages: list[dict[str, str]], **_kwargs: Any) -> AiCompletion:
        payload = {
            "variant": "error_contrast",
            "language": "java",
            "title": "División por cero en Calculadora",
            "source_code": calc_source,
            "fixed_code": calc_fixed,
            "subgoals": [
                {"id": "s1", "label": "Ejecución con fallo"},
                {"id": "s2", "label": "Corrección defensiva"},
            ],
            "steps": [
                {
                    "index": 0,
                    "subgoal_id": "s1",
                    "active_lines": [6],
                    "caption": "main invoca dividir(10, 0).",
                    "checkpoint": {"enabled": False},
                    "state": {
                        "phase": "buggy_run",
                        "code_view": "broken",
                        "exception": None,
                        "call_stack": [{"frame": "main()", "status": "active", "line": 6}],
                        "contrast": {
                            "bug_cause": "Spoiler indebido en buggy_run",
                            "broken_line": "return a / b;",
                            "fixed_line": "if (b == 0) ...",
                        },
                    },
                },
                {
                    "index": 1,
                    "subgoal_id": "s1",
                    "active_lines": [3],
                    "caption": "dividir intenta calcular 10 / 0.",
                    "checkpoint": {
                        "enabled": True,
                        "question": "¿Qué excepción lanza 10 / 0 en Java?",
                        "options": ["ArithmeticException", "IndexOutOfBoundsException"],
                        "correct_index": 0,
                        "explanation": "La división entera por cero lanza ArithmeticException.",
                    },
                    "state": {
                        "phase": "buggy_run",
                        "code_view": "broken",
                        "exception": {
                            "type": "ArithmeticException",
                            "message": "/ by zero",
                            "line": 3,
                        },
                        "call_stack": [
                            {"frame": "main()", "status": "active", "line": 6},
                            {"frame": "Calculadora.dividir(10, 0)", "status": "crashed", "line": 3},
                        ],
                    },
                },
                {
                    "index": 2,
                    "subgoal_id": "s1",
                    "active_lines": [3],
                    "caption": "ArithmeticException desenrolla la pila.",
                    "checkpoint": {"enabled": False},
                    "state": {
                        "phase": "stack_unwinding",
                        "code_view": "broken",
                        "exception": {
                            "type": "ArithmeticException",
                            "message": "/ by zero",
                            "line": 3,
                        },
                        "call_stack": [{"frame": "Calculadora.dividir(10, 0)", "status": "unwinding", "line": 3}],
                    },
                },
                {
                    "index": 3,
                    "subgoal_id": "s2",
                    "active_lines": [3],
                    "caption": "Validar b == 0 evita la excepción inesperada.",
                    "checkpoint": {"enabled": False},
                    "state": {
                        "phase": "fixed_diff",
                        "code_view": "fixed",
                        "exception": None,
                        "call_stack": [{"frame": "Calculadora.dividir(10, 2)", "status": "ok", "line": 4}],
                        # contrast deliberadamente ausente para probar derivacion desde source_code/fixed_code
                    },
                },
                {
                    "index": 4,
                    "subgoal_id": "s2",
                    "active_lines": [7],
                    "caption": "main imprime el resultado válido 5.",
                    "checkpoint": {"enabled": False},
                    "state": {
                        "phase": "fixed_diff",
                        "code_view": "fixed",
                        "exception": None,
                        "call_stack": [{"frame": "main()", "status": "ok", "line": 7}],
                    },
                },
            ],
        }
        return AiCompletion(text=json.dumps(payload), provider="groq", model="llama-3.3-70b-versatile")

    monkeypatch.setattr(ai_router, "complete_chat", fake_calc_with_fix)

    res = client.post(f"/api/v1/study/{_STORYBOARD_COURSE}/ERR/storyboard?force=true")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provider"] == "groq"
    assert body["variant"] == "error_contrast"

    serialized = json.dumps(body, ensure_ascii=False)
    assert "texto.trim()" not in serialized
    assert "NullPointerException" not in serialized
    assert "ValidadorCodigo" not in serialized
    assert body["fixed_code"] is not None
    assert "Calculadora" in body["fixed_code"]

    for step in body["steps"]:
        st = step["state"]
        if st["phase"] in ("buggy_run", "running", "exception_thrown", "stack_unwinding", "caught"):
            assert "contrast" not in st
        elif st["phase"] == "fixed_diff":
            assert "contrast" in st
            assert "b == 0" in st["contrast"]["fixed_line"]
            assert "texto.trim()" not in st["contrast"]["broken_line"]

    # Caso 2: IA omite fixed_code -> NO se sustituye por fallback NullPointerException y contrast queda ausente
    def fake_calc_without_fixed(_messages: list[dict[str, str]], **_kwargs: Any) -> AiCompletion:
        payload = {
            "variant": "error_contrast",
            "language": "java",
            "title": "División por cero sin fixed_code",
            "source_code": calc_source,
            "fixed_code": None,
            "subgoals": [{"id": "s1", "label": "Fallo"}, {"id": "s2", "label": "Cierre"}],
            "steps": [
                {
                    "index": i,
                    "subgoal_id": "s1" if i < 3 else "s2",
                    "active_lines": [3],
                    "caption": f"Paso {i} de Calculadora.",
                    "checkpoint": {"enabled": False},
                    "state": {
                        "phase": "buggy_run" if i < 3 else "fixed_diff",
                        "code_view": "broken" if i < 3 else "fixed",
                        "exception": (
                            {"type": "ArithmeticException", "message": "/ by zero", "line": 3}
                            if i == 1
                            else None
                        ),
                        "call_stack": [{"frame": "Calculadora.dividir()", "status": "active", "line": 3}],
                    },
                }
                for i in range(5)
            ],
        }
        return AiCompletion(text=json.dumps(payload), provider="groq", model="llama-3.3-70b-versatile")

    monkeypatch.setattr(ai_router, "complete_chat", fake_calc_without_fixed)
    res2 = client.post(f"/api/v1/study/{_STORYBOARD_COURSE}/ERR/storyboard?force=true")
    assert res2.status_code == 200, res2.text
    body2 = res2.json()
    assert body2["fixed_code"] is None
    serialized2 = json.dumps(body2, ensure_ascii=False)
    assert "texto.trim()" not in serialized2
    assert "NullPointerException" not in serialized2
    assert all("contrast" not in s["state"] for s in body2["steps"])


def test_cinema_reel_end_to_end_audio_stream_and_story_regeneration_preservation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import study as study_router
    from app.services.tts import cinema_act_audio_path

    _install_storyboard_pack(client)
    base = f"/api/v1/study/{_STORYBOARD_COURSE}/OOP"

    # 1. GET /cinema-reel devuelve 404 antes de generarse (y para nodos/cursos inexistentes)
    assert client.get(f"{base}/cinema-reel").status_code == 404
    assert client.get(f"/api/v1/study/{_STORYBOARD_COURSE}/NOPE/cinema-reel").status_code == 404
    assert client.get(f"{base}/cinema-reel/audio/0").status_code == 404
    assert client.get(f"/api/v1/study/{_STORYBOARD_COURSE}/NOPE/cinema-reel/stream").status_code == 404

    # Mock de synthesize_cinema_act_audios para no depender de red y escribir MP3 dummy en cache
    synth_calls: list[list[str]] = []

    async def fake_synthesize_cinema_act_audios(
        course_id: str,
        texts: list[str],
        voice: str | None = None,
    ) -> list[Path | None]:
        synth_calls.append(list(texts))
        out: list[Path | None] = []
        for idx, txt in enumerate(texts):
            p = cinema_act_audio_path(course_id, txt, voice)
            p.write_bytes(f"ID3-CINEMA-ACT-{idx}".encode())
            out.append(p)
        return out

    monkeypatch.setattr(study_router, "synthesize_cinema_act_audios", fake_synthesize_cinema_act_audios)

    # 2. POST /cinema-reel genera 5 actos en orden estricto, persiste y devuelve audio_url
    created = client.post(f"{base}/cinema-reel")
    assert created.status_code == 200, created.text
    reel = created.json()
    assert reel["course_id"] == _STORYBOARD_COURSE
    assert reel["node_id"] == "OOP"
    assert reel["provider"] == "local_fallback"
    assert len(reel["acts"]) == 5
    assert [a["index"] for a in reel["acts"]] == [0, 1, 2, 3, 4]
    assert [a["kind"] for a in reel["acts"]] == ["hook", "analogy", "mechanism", "payoff", "takeaway"]
    assert len(reel["acts"][4]["pills"]) == 3
    for i, act in enumerate(reel["acts"]):
        assert act["audio_url"] == f"/api/v1/study/{_STORYBOARD_COURSE}/OOP/cinema-reel/audio/{i}"
        assert 5.0 <= act["estimated_sec"] <= 25.0
    assert len(synth_calls) == 1

    # GET /cinema-reel devuelve exactamente lo persistido con audio_url activo
    fetched = client.get(f"{base}/cinema-reel")
    assert fetched.status_code == 200
    assert fetched.json() == reel

    # Segundo POST sin force usa cache sin volver a sintetizar
    cached_post = client.post(f"{base}/cinema-reel")
    assert cached_post.status_code == 200
    assert cached_post.json()["updated_at"] == reel["updated_at"]
    assert len(synth_calls) == 1

    # 3. GET /cinema-reel/audio/{act_index} devuelve 200 audio/mpeg con bytes esperados; invalido -> 404
    audio0 = client.get(f"{base}/cinema-reel/audio/0")
    assert audio0.status_code == 200
    assert audio0.headers["content-type"].startswith("audio/mpeg")
    assert audio0.content == b"ID3-CINEMA-ACT-0"

    assert client.get(f"{base}/cinema-reel/audio/5").status_code == 404
    assert client.get(f"{base}/cinema-reel/audio/-1").status_code == 404

    # 4. GET /cinema-reel/stream en nodo nuevo emite hitos 15 -> 55 -> 88 -> 100 sin database is locked
    stream_res = client.get(f"/api/v1/study/{_STORYBOARD_COURSE}/DS/cinema-reel/stream")
    assert stream_res.status_code == 200
    assert stream_res.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(stream_res.text)
    assert [e["stage"] for e in events] == ["analyzing", "scripting", "synthesizing_audio", "done"]
    assert [e["pct"] for e in events] == [15, 55, 88, 100]
    streamed_reel = events[-1]["reel"]
    assert [a["kind"] for a in streamed_reel["acts"]] == ["hook", "analogy", "mechanism", "payoff", "takeaway"]
    assert all(a["audio_url"] for a in streamed_reel["acts"])

    # Confirmar persistencia en SQLite desde la conexion dedicada del stream
    stored_ds = client.get(f"/api/v1/study/{_STORYBOARD_COURSE}/DS/cinema-reel")
    assert stored_ds.status_code == 200
    assert stored_ds.json()["updated_at"] == streamed_reel["updated_at"]

    # 5. Tras POST /regenerate-story, GET /cinema-reel sigue intacto (preservacion)
    regen = client.post(f"{base}/regenerate-story")
    assert regen.status_code == 200
    still_there = client.get(f"{base}/cinema-reel")
    assert still_there.status_code == 200
    assert still_there.json()["updated_at"] == reel["updated_at"]
    assert still_there.json()["acts"] == reel["acts"]


def test_synthesize_cinema_act_audios_parallel_cache_and_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import asyncio

    from app.services import tts

    monkeypatch.setenv("BROTAL_HOME", str(tmp_path))
    edge_calls: list[tuple[str, str]] = []

    async def fake_edge(text: str, voice: str, out_path: Path) -> dict[str, Any]:
        edge_calls.append((text, voice))
        if "FALLAR" in text:
            raise RuntimeError("offline")
        out_path.write_bytes(f"MP3::{text}".encode())
        return {"sentences": [], "words": []}

    monkeypatch.setattr(tts, "_run_edge_tts", fake_edge)

    texts = ["Acto uno narrado", "Acto dos FALLAR", "Acto tres narrado"]
    paths = asyncio.run(tts.synthesize_cinema_act_audios("curso-test", texts))
    assert len(paths) == 3
    assert paths[0] is not None and paths[0].is_file()
    assert paths[1] is None
    assert paths[2] is not None and paths[2].is_file()

    # Segunda ejecucion usa cache para los actos exitosos sin volver a llamar edge-tts en ellos
    prev_ok_calls = sum(1 for t, _v in edge_calls if "FALLAR" not in t)
    paths2 = asyncio.run(tts.synthesize_cinema_act_audios("curso-test", [texts[0], texts[2]]))
    after_ok_calls = sum(1 for t, _v in edge_calls if "FALLAR" not in t)
    assert paths2[0] == paths[0]
    assert paths2[1] == paths[2]
    assert after_ok_calls == prev_ok_calls


def test_sample_chunks_balanced_15_sections_keeps_first_and_last_with_full_coverage() -> None:
    from app.services.ingest import (
        _sample_chunks_balanced,
        _sample_chunks_with_stats,
        extract_chunks_from_bytes,
    )

    sections = [
        f"## Tema {i:02d}: Fundamento numero {i}\n"
        f"Contenido tecnico detallado de la seccion {i:02d} con marcador SECCION_MARCA_{i:02d} "
        f"para verificar que ningun tramo del documento sea omitido en el muestreo.\n"
        for i in range(1, 16)
    ]
    md_bytes = "\n\n".join(sections).encode("utf-8")
    chunks = extract_chunks_from_bytes("guia_15_temas.md", md_bytes)
    assert len(chunks) == 15

    digest = _sample_chunks_balanced(chunks)
    assert "SECCION_MARCA_01" in digest
    assert "SECCION_MARCA_08" in digest
    assert "SECCION_MARCA_15" in digest

    digest_stats, stats = _sample_chunks_with_stats(chunks)
    assert digest_stats == digest
    assert stats["total_chunks"] == 15
    assert stats["sampled_chunks"] == 15
    assert stats["total_chars"] == stats["sampled_chars"]
    assert stats["coverage_pct"] == 100
    assert stats["coverage_warning"] is None


def test_extract_chunks_subdivides_long_single_heading_markdown_without_truncation() -> None:
    from app.services.ingest import extract_chunks_from_bytes

    # ~9500 caracteres bajo un unico encabezado '#'
    paragraphs = [
        f"Parrafo {i:02d}: " + ("Explicacion detallada de arquitectura de computadores y memoria cache. " * 7)
        for i in range(1, 19)
    ]
    final_marker = "PARRAFO_FINAL_VERIFICABLE: cierre completo de la guia sin perdida de contenido."
    paragraphs.append(final_marker)
    raw_body = "\n\n".join(paragraphs)
    assert len(raw_body) > 9000

    long_md = f"# Guia Unica de Arquitectura\n\n{raw_body}\n".encode()
    chunks = extract_chunks_from_bytes("guia_unica.md", long_md)

    assert len(chunks) >= 3
    assert chunks[0].section_title == "Guia Unica de Arquitectura (parte 1)"
    assert chunks[1].section_title == "Guia Unica de Arquitectura (parte 2)"
    assert chunks[-1].section_title == f"Guia Unica de Arquitectura (parte {len(chunks)})"
    assert all(len(c.content) <= 3500 for c in chunks)
    assert final_marker in chunks[-1].content
    assert "Parrafo 01:" in chunks[0].content

    # Una seccion corta (<= 3200 chars) mantiene comportamiento normal (1 chunk con el heading exacto)
    short_md = b"# Seccion Corta\n\nResumen conciso de memoria virtual y paginacion en sistemas operativos.\n"
    short_chunks = extract_chunks_from_bytes("corta.md", short_md)
    assert len(short_chunks) == 1
    assert short_chunks[0].section_title == "Seccion Corta"


def test_sample_chunks_uniform_40_chunks_with_max_chunks_10_includes_start_middle_and_end() -> None:
    from app.services.ingest import (
        ExtractedChunk,
        _sample_chunks_balanced,
        _sample_chunks_with_stats,
    )

    chunks = [
        ExtractedChunk(
            source_file="curso_extenso.md",
            section_title=f"Unidad {i}",
            content=f"Contenido de la unidad {i} con token UNIDAD_TOKEN_{i:02d}. " + ("Detalle tecnico. " * 12),
        )
        for i in range(40)
    ]

    digest_text, stats = _sample_chunks_with_stats(chunks, max_chunks=10, max_chars=36000)
    assert digest_text == _sample_chunks_balanced(chunks, max_chunks=10, max_chars=36000)
    assert stats["total_chunks"] == 40
    assert stats["sampled_chunks"] == 10
    assert stats["coverage_pct"] < 85
    assert stats["coverage_warning"] is not None
    assert f"{stats['coverage_pct']}%" in stats["coverage_warning"]
    assert "Agregar al árbol" in stats["coverage_warning"]

    # Indice 0, zona intermedia (17/22) e indice 39 (ultimo) deben estar presentes
    assert "UNIDAD_TOKEN_00" in digest_text
    assert any(f"UNIDAD_TOKEN_{mid:02d}" in digest_text for mid in range(15, 25))
    assert "UNIDAD_TOKEN_39" in digest_text


def test_ingest_local_endpoint_returns_coverage_metrics_in_replace_and_append(client: TestClient) -> None:
    # 1. Mode replace con material normal -> coverage_pct == 100 y coverage_warning == None
    normal_md = (
        b"# Unidad 1: Procesos e Hilos\n"
        b"Un proceso posee espacio de direcciones aislado mientras los hilos comparten heap y codigo.\n\n"
        b"# Unidad 2: Planificacion de CPU\n"
        b"Los planificadores Round Robin y MLFQ equilibran latencia de respuesta y rendimiento total.\n"
    )
    res_replace = client.post(
        "/api/v1/courses/ingest-local",
        data={
            "course_code": "INF2440",
            "title": "Sistemas Operativos",
            "mode": "replace",
        },
        files=[("files", ("so_unidad1.md", normal_md, "text/markdown"))],
    )
    assert res_replace.status_code == 200, res_replace.text
    d_rep = res_replace.json()
    assert d_rep["mode"] == "replace"
    assert d_rep["total_chunks"] == 2
    assert d_rep["sampled_chunks"] == 2
    assert d_rep["total_chars"] > 0
    assert d_rep["sampled_chars"] == d_rep["total_chars"]
    assert d_rep["coverage_pct"] == 100
    assert d_rep["coverage_warning"] is None

    # 2. Mode append con material extenso (> 36000 chars) -> coverage_pct < 85 y coverage_warning no vacio
    big_sections = [
        f"## Capitulo {i:02d}: Memoria Virtual y Sistemas de Archivos\n"
        + (f"Explicacion tecnica profunda del capitulo {i:02d} sobre paginacion, TLB e inodos. " * 22)
        for i in range(1, 36)
    ]
    big_md = "\n\n".join(big_sections).encode("utf-8")
    res_append = client.post(
        "/api/v1/courses/ingest-local",
        data={
            "course_code": "INF2440",
            "title": "Sistemas Operativos",
            "mode": "append",
        },
        files=[("files", ("so_extenso.md", big_md, "text/markdown"))],
    )
    assert res_append.status_code == 200, res_append.text
    d_app = res_append.json()
    assert d_app["mode"] == "append"
    assert d_app["total_chunks"] == 35
    assert d_app["total_chars"] > 45000
    assert 0 < d_app["sampled_chars"] < d_app["total_chars"]
    assert 0 <= d_app["coverage_pct"] < 85
    assert isinstance(d_app["coverage_warning"], str)
    assert f"{d_app['coverage_pct']}%" in d_app["coverage_warning"]
    assert "Chat Tutor" in d_app["coverage_warning"]
