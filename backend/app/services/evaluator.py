"""Rubrica 7/10 y cooldown 0/3 -> 3/3 vs Reps (Issue #4).

Reglas (CONTRATO-V0.1 seccion 4):
- passed = score >= PASS_SCORE (7.0).
- Si passed y NO hay cooldown activo (next_review_at es NULL o ya vencio):
  mastery_level += 1 (max 3), counted_mastery=1, next_review_at = ahora + cooldown segun
  user_profile.cooldown_mode ('semester' | 'urgency').
- Si passed pero hay cooldown activo (o ya esta en 3/3): training_reps += 1, mastery_level NO cambia, counted_mastery=0.
- Siempre: best_score = max(best_score, score), last_score, last_practiced_at; se inserta una fila
  en evaluation_attempts.
- Logica pura (inyectar "now") para testear sin reloj real.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

PASS_SCORE = 7.0
MAX_MASTERY = 3

_STOP_WORDS = {
    "identifica", "explica", "menciona", "distingue", "relaciona", "justifica",
    "define", "describe", "ejemplo", "valido", "para", "como", "este", "esta",
    "esto", "sobre", "entre", "desde", "cada", "tiene", "tambien", "porque",
    "cual", "cuales", "que", "los", "las", "una", "uno", "unos", "unas", "del",
    "con", "por", "sus", "ser", "son", "sin", "mas", "muy",
}


@dataclass
class EvalResult:
    score: float
    passed: bool
    counted_mastery: bool
    mastery_level: int
    training_reps: int
    next_review_at: datetime | None
    best_score: float = 0.0


def _cooldown_delta(cooldown_mode: str, new_mastery_level: int) -> timedelta:
    if cooldown_mode == "semester":
        return timedelta(days=7) if new_mastery_level <= 1 else timedelta(days=30)
    if cooldown_mode == "urgency":
        sec = int(os.environ.get("BROTAL_URGENCY_COOLDOWN_SEC", "30"))
        return timedelta(seconds=sec)
    raise ValueError(f"Invalid cooldown_mode '{cooldown_mode}'")


def apply_evaluation(
    *,
    mastery_level: int,
    training_reps: int,
    best_score: float,
    next_review_at: datetime | None,
    score: float,
    cooldown_mode: str,
    now: datetime,
) -> EvalResult:
    clamped_score = round(max(1.0, min(10.0, float(score))), 1)
    passed = clamped_score >= PASS_SCORE
    new_best = max(float(best_score), clamped_score)
    in_cooldown = next_review_at is not None and next_review_at > now

    if passed:
        if not in_cooldown and mastery_level < MAX_MASTERY:
            new_mastery = mastery_level + 1
            counted_mastery = True
            new_reps = training_reps
            new_next_review = now + _cooldown_delta(cooldown_mode, new_mastery)
        else:
            new_mastery = mastery_level
            counted_mastery = False
            new_reps = training_reps + 1
            new_next_review = next_review_at
    else:
        new_mastery = mastery_level
        counted_mastery = False
        new_reps = training_reps
        new_next_review = next_review_at

    return EvalResult(
        score=clamped_score,
        passed=passed,
        counted_mastery=counted_mastery,
        mastery_level=new_mastery,
        training_reps=new_reps,
        next_review_at=new_next_review,
        best_score=new_best,
    )


def _norm(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in nfd if not unicodedata.combining(ch))


def _keywords(point: str) -> tuple[list[str], list[str]]:
    acronyms = [_norm(m) for m in re.findall(r"\b[A-Z][A-Z0-9-]{1,}\b", point)]
    words = [w for w in re.split(r"[^a-z0-9]+", _norm(point)) if len(w) >= 4 and w not in _STOP_WORDS]
    stems = list(dict.fromkeys(w[:5] for w in words))
    return stems, acronyms


def score_from_feedback(feedback: list[dict[str, Any]]) -> float:
    if not feedback:
        return 1.0
    covered_count = sum(1 for item in feedback if item.get("covered"))
    ratio = covered_count / len(feedback)
    return round(1.0 + 9.0 * ratio, 1)


def evaluate_rubric(
    eval_prompts: list[dict[str, Any]],
    answers_by_prompt: dict[str, str],
    covered_points: list[str] | None = None,
) -> list[dict[str, Any]]:
    covered_set = set(covered_points) if covered_points is not None else None
    feedback: list[dict[str, Any]] = []

    for q in eval_prompts:
        qid = str(q["id"])
        rubric_points: list[str] = list(q.get("rubric_points", []))
        ans_norm = _norm(answers_by_prompt.get(qid, ""))
        ans_words = [w for w in re.split(r"[^a-z0-9]+", ans_norm) if w]

        for idx, point in enumerate(rubric_points):
            if covered_set is not None:
                is_covered = f"{qid}::{idx}" in covered_set
            else:
                stems, acronyms = _keywords(point)
                has_acr = all(a in ans_words for a in acronyms)
                hits = sum(1 for s in stems if any(w.startswith(s) for w in ans_words))
                is_covered = bool(ans_norm) and has_acr and (not stems or (hits / len(stems)) >= 0.5)

            feedback.append(
                {
                    "prompt_id": qid,
                    "point_index": idx,
                    "point": point,
                    "covered": is_covered,
                }
            )
    return feedback
