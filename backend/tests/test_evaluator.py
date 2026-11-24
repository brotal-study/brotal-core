from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.config import fixtures_dir
from app.services.evaluator import apply_evaluation


def test_apply_evaluation_exact_7_0_and_below() -> None:
    now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)

    # 6.9 fails and does not drop mastery_level
    fail = apply_evaluation(
        mastery_level=2,
        training_reps=1,
        best_score=8.0,
        next_review_at=None,
        score=6.9,
        cooldown_mode="semester",
        now=now,
    )
    assert fail.passed is False
    assert fail.counted_mastery is False
    assert fail.mastery_level == 2
    assert fail.training_reps == 1
    assert fail.best_score == 8.0

    # Exact 7.0 passes and increments mastery_level when not in cooldown
    ok = apply_evaluation(
        mastery_level=0,
        training_reps=0,
        best_score=0.0,
        next_review_at=None,
        score=7.0,
        cooldown_mode="semester",
        now=now,
    )
    assert ok.passed is True
    assert ok.counted_mastery is True
    assert ok.mastery_level == 1
    assert ok.training_reps == 0
    assert ok.best_score == 7.0
    assert ok.next_review_at == now + timedelta(days=7)


def test_apply_evaluation_cooldown_active_vs_expired_and_cap_3_of_3() -> None:
    t0 = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)

    # First validation: 0/3 -> 1/3 (semester mode: +7 days)
    r1 = apply_evaluation(
        mastery_level=0,
        training_reps=0,
        best_score=0.0,
        next_review_at=None,
        score=8.0,
        cooldown_mode="semester",
        now=t0,
    )
    assert r1.mastery_level == 1
    assert r1.counted_mastery is True
    assert r1.next_review_at == t0 + timedelta(days=7)

    # During active cooldown (+1 day): passing increments training_reps, NOT mastery_level
    r_cool = apply_evaluation(
        mastery_level=r1.mastery_level,
        training_reps=r1.training_reps,
        best_score=r1.best_score,
        next_review_at=r1.next_review_at,
        score=9.5,
        cooldown_mode="semester",
        now=t0 + timedelta(days=1),
    )
    assert r_cool.passed is True
    assert r_cool.counted_mastery is False
    assert r_cool.mastery_level == 1
    assert r_cool.training_reps == 1
    assert r_cool.best_score == 9.5

    # After cooldown expires (+7 days): passing increments 1/3 -> 2/3 (+30 days in semester mode)
    t2 = t0 + timedelta(days=7, seconds=1)
    r2 = apply_evaluation(
        mastery_level=r_cool.mastery_level,
        training_reps=r_cool.training_reps,
        best_score=r_cool.best_score,
        next_review_at=r_cool.next_review_at,
        score=8.5,
        cooldown_mode="semester",
        now=t2,
    )
    assert r2.counted_mastery is True
    assert r2.mastery_level == 2
    assert r2.training_reps == 1
    assert r2.next_review_at == t2 + timedelta(days=30)

    # Third validation after cooldown: 2/3 -> 3/3
    t3 = t2 + timedelta(days=30, seconds=1)
    r3 = apply_evaluation(
        mastery_level=r2.mastery_level,
        training_reps=r2.training_reps,
        best_score=r2.best_score,
        next_review_at=r2.next_review_at,
        score=10.0,
        cooldown_mode="semester",
        now=t3,
    )
    assert r3.counted_mastery is True
    assert r3.mastery_level == 3

    # Once at 3/3, even after cooldown expires, mastery stays capped at 3 and training_reps increments
    t4 = t3 + timedelta(days=60)
    r4 = apply_evaluation(
        mastery_level=r3.mastery_level,
        training_reps=r3.training_reps,
        best_score=r3.best_score,
        next_review_at=r3.next_review_at,
        score=9.0,
        cooldown_mode="semester",
        now=t4,
    )
    assert r4.passed is True
    assert r4.counted_mastery is False
    assert r4.mastery_level == 3
    assert r4.training_reps == 2


def test_apply_evaluation_urgency_mode() -> None:
    now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)
    res = apply_evaluation(
        mastery_level=0,
        training_reps=0,
        best_score=0.0,
        next_review_at=None,
        score=7.5,
        cooldown_mode="urgency",
        now=now,
    )
    assert res.counted_mastery is True
    assert res.mastery_level == 1
    assert res.next_review_at is not None
    assert res.next_review_at < now + timedelta(hours=1)


def test_study_tree_and_evaluate_endpoint(client: TestClient) -> None:
    demo_pack = json.loads((fixtures_dir() / "demo_pack.json").read_text(encoding="utf-8"))
    client.post("/api/v1/courses/install-pack", json=demo_pack)

    tree_res = client.get("/api/v1/courses/cl-pucv-inf2324-ccna1/tree")
    assert tree_res.status_code == 200
    tree = tree_res.json()
    assert len(tree["nodes"]) == 4
    assert tree["progress"]["B1-P2"]["mastery_level"] == 0

    # Evaluate B1-P2 with covered_points
    ev1 = client.post(
        "/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/evaluate",
        json={
            "answers": [
                {"prompt_id": "q1", "text": "OSI es modelo teorico de 7 capas y TCP/IP practico de 4 capas"},
                {"prompt_id": "q2", "text": "IEEE e IETF definen estandares abiertos para interoperabilidad"},
            ],
            "covered_points": ["q1::0", "q1::1", "q1::2", "q2::0", "q2::1"],
            "cooldown_mode": "semester",
        },
    )
    assert ev1.status_code == 200
    b1 = ev1.json()
    assert b1["score"] == 10.0
    assert b1["passed"] is True
    assert b1["counted_mastery"] is True
    assert b1["progress"]["mastery_level"] == 1
    assert b1["progress"]["training_reps"] == 0

    # Immediate second evaluation while in cooldown increments training_reps, not mastery_level
    ev2 = client.post(
        "/api/v1/study/cl-pucv-inf2324-ccna1/B1-P2/evaluate",
        json={
            "answers": [
                {"prompt_id": "q1", "text": "OSI teorico 7 capas y TCP/IP practico 4 capas"},
                {"prompt_id": "q2", "text": "Estandares abiertos e interoperabilidad"},
            ],
            "covered_points": ["q1::0", "q1::1", "q1::2", "q2::0", "q2::1"],
            "cooldown_mode": "semester",
        },
    )
    assert ev2.status_code == 200
    b2 = ev2.json()
    assert b2["passed"] is True
    assert b2["counted_mastery"] is False
    assert b2["progress"]["mastery_level"] == 1
    assert b2["progress"]["training_reps"] == 1

    # Reset progress endpoint
    rst = client.post("/api/v1/courses/cl-pucv-inf2324-ccna1/reset-progress")
    assert rst.status_code == 200
    tree_after = client.get("/api/v1/courses/cl-pucv-inf2324-ccna1/tree").json()
    assert tree_after["progress"]["B1-P2"]["mastery_level"] == 0
    assert tree_after["progress"]["B1-P2"]["training_reps"] == 0
