from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from app.config import db_path, fixtures_dir, tts_cache_dir


def test_install_pack_idempotent_archive_and_export(client: TestClient) -> None:
    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))

    # Install first time
    r1 = client.post("/api/v1/courses/install-pack", json=demo_pack)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["course_id"] == "cl-pucv-inf2324-ccna1"
    assert d1["status"] == "active"

    # Install second time (idempotent, must not duplicate courses or nodes)
    r2 = client.post("/api/v1/courses/install-pack", json=demo_pack)
    assert r2.status_code == 200

    active_courses = client.get("/api/v1/courses?status=active").json()
    assert len(active_courses) == 1
    assert active_courses[0]["id"] == "cl-pucv-inf2324-ccna1"

    tree = client.get("/api/v1/courses/cl-pucv-inf2324-ccna1/tree").json()
    assert len(tree["nodes"]) == 4
    assert all(p["mastery_level"] == 0 for p in tree["progress"].values())

    # Simulate an evaluation attempt + TTS cache file + FTS chunk before archiving
    eval_res = client.post(
        "/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/evaluate",
        json={"answers": [{"prompt_id": "q1", "text": "OSI 7 capas TCP/IP 4"}], "score": 9.0},
    )
    assert eval_res.status_code == 200
    assert eval_res.json()["progress"]["mastery_level"] == 1

    fake_tts_dir = tts_cache_dir() / "cl-pucv-inf2324-ccna1"
    fake_tts_dir.mkdir(parents=True, exist_ok=True)
    fake_mp3 = fake_tts_dir / "B1-P2.mp3"
    fake_mp3.write_bytes(b"ID3-fake-audio")

    with sqlite3.connect(str(db_path())) as conn:
        conn.execute(
            "INSERT INTO local_chunks_fts (course_id, source_file, section_title, content) VALUES (?, ?, ?, ?);",
            ("cl-pucv-inf2324-ccna1", "secret.pdf", "Intro", "Contenido privado con copyright"),
        )
        conn.commit()

    # Archive course: deletes TTS cache and FTS chunks, preserves node_progress and evaluation_attempts
    arch = client.patch(
        "/api/v1/courses/cl-pucv-inf2324-ccna1",
        json={"status": "archived"},
    )
    assert arch.status_code == 200
    assert arch.json()["status"] == "archived"
    assert not fake_mp3.exists()

    with sqlite3.connect(str(db_path())) as conn:
        fts_cnt = conn.execute(
            "SELECT COUNT(*) FROM local_chunks_fts WHERE course_id = 'cl-pucv-inf2324-ccna1';"
        ).fetchone()[0]
        assert fts_cnt == 0
        att_cnt = conn.execute(
            "SELECT COUNT(*) FROM evaluation_attempts WHERE course_id = 'cl-pucv-inf2324-ccna1';"
        ).fetchone()[0]
        assert att_cnt == 1
        lvl = conn.execute(
            "SELECT mastery_level FROM node_progress WHERE course_id = 'cl-pucv-inf2324-ccna1' AND node_id = 'B1-P2';"
        ).fetchone()[0]
        assert lvl == 1

    # Export clean pack and reinstall
    exp = client.get("/api/v1/courses/cl-pucv-inf2324-ccna1/export")
    assert exp.status_code == 200
    exported_pack = exp.json()
    assert exported_pack["schema_version"] == "1.0"
    assert exported_pack["id"] == "cl-pucv-inf2324-ccna1"
    assert len(exported_pack["nodes"]) == 4
    assert "secret.pdf" not in json.dumps(exported_pack)

    reinstall = client.post("/api/v1/courses/install-pack", json=exported_pack)
    assert reinstall.status_code == 200
    tree_after = client.get("/api/v1/courses/cl-pucv-inf2324-ccna1/tree").json()
    assert [n["id"] for n in tree_after["nodes"]] == [n["id"] for n in tree["nodes"]]
    # Existing mastery_level is preserved on reinstall
    assert tree_after["progress"]["B1-P2"]["mastery_level"] == 1


def test_install_pack_invalid_schema_returns_422(client: TestClient) -> None:
    bad_pack = {
        "schema_version": "2.0",
        "id": "bad-pack",
        "course_code": "BAD101",
        "title": "Invalid Pack",
    }
    res = client.post("/api/v1/courses/install-pack", json=bad_pack)
    assert res.status_code == 422


def test_manual_course_lifecycle(client: TestClient) -> None:
    created = client.post(
        "/api/v1/courses/manual",
        json={"code": "RUST101", "name": "Programacion en Rust", "credits": 4, "category": "inf"},
    )
    assert created.status_code == 201
    c = created.json()
    assert c["manual"] is True
    assert c["code"] == "RUST101"

    patched = client.patch(f"/api/v1/courses/{c['id']}", json={"status": "active"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "active"

    deleted = client.delete(f"/api/v1/courses/{c['id']}")
    assert deleted.status_code == 200
