"""Rubrica 7/10 y cooldown 0/3 -> 3/3 vs Reps. STUB - Issue #4.

Reglas (CONTRATO-V0.1 seccion 4):
- passed = score >= PASS_SCORE (7.0).
- Si passed y NO hay cooldown activo (next_review_at es NULL o ya vencio):
  mastery_level += 1 (max 3), counted_mastery=1, next_review_at = ahora + cooldown segun
  user_profile.cooldown_mode ('semester' | 'urgency').
- Si passed pero hay cooldown activo: training_reps += 1, mastery_level NO cambia, counted_mastery=0.
- Siempre: best_score = max(best_score, score), last_score, last_practiced_at; se inserta una fila
  en evaluation_attempts.
- Debe ser logica pura (inyectar "now") para testear sin reloj real.
"""
from dataclasses import dataclass
from datetime import datetime

PASS_SCORE = 7.0
MAX_MASTERY = 3


@dataclass
class EvalResult:
    score: float
    passed: bool
    counted_mastery: bool
    mastery_level: int
    training_reps: int
    next_review_at: datetime | None


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
    raise NotImplementedError("Issue #4")
