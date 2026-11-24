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
