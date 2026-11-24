"""Router de perfil local /api/v1/profile (Issue #2)."""
from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.config import configured_providers
from app.db.database import get_conn
from app.schemas.profile import Profile, ProfilePatch, ProvidersStatus

router = APIRouter(tags=["profile"])

DbConn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _row_to_profile(row: sqlite3.Row) -> Profile:
    return Profile(
        id=row["id"],
        display_name=row["display_name"],
        career_id=row["career_id"],
        curriculum_mode=row["curriculum_mode"],
        cooldown_mode=row["cooldown_mode"],
        theme=row["theme"],
        ai_provider=row["ai_provider"],
        created_at=row["created_at"],
        providers=ProvidersStatus(**configured_providers()),
    )


@router.get("/profile", response_model=Profile)
def get_profile(conn: DbConn) -> Profile:
    conn.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1);")
    row = conn.execute("SELECT * FROM user_profile WHERE id = 1;").fetchone()
    assert row is not None
    return _row_to_profile(row)


@router.patch("/profile", response_model=Profile)
def patch_profile(
    patch: ProfilePatch,
    conn: DbConn,
) -> Profile:
    conn.execute("INSERT OR IGNORE INTO user_profile (id) VALUES (1);")
    updates: dict[str, Any] = {}
    for field in patch.model_fields_set:
        val = getattr(patch, field)
        if field != "career_id" and val is None:
            raise HTTPException(status_code=422, detail=f"Field '{field}' cannot be null")
        if field == "display_name" and isinstance(val, str):
            val = val.strip()
            if not val:
                raise HTTPException(status_code=422, detail="display_name cannot be empty")
        updates[field] = val

    if updates:
        cols = ", ".join(f"{col} = ?" for col in updates)
        params = [*updates.values(), 1]
        conn.execute(f"UPDATE user_profile SET {cols} WHERE id = ?;", params)
        conn.commit()

    row = conn.execute("SELECT * FROM user_profile WHERE id = 1;").fetchone()
    assert row is not None
    return _row_to_profile(row)
