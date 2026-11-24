"""Entrypoint FastAPI de Brotal (v1.0)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import REPO_ROOT
from app.db.database import init_db
from app.routers import chat, courses, profile, registry, settings, study


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Brotal API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


app.include_router(profile.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")
app.include_router(registry.router, prefix="/api/v1")
app.include_router(courses.router, prefix="/api/v1")
app.include_router(study.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend-assets")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_spa(full_path: str) -> FileResponse:
    if full_path.startswith("api/") or full_path in ("openapi.json", "docs", "redoc"):
        raise HTTPException(status_code=404, detail="Not Found")
    index_file = FRONTEND_DIST / "index.html"
    if not index_file.is_file():
        raise HTTPException(
            status_code=404,
            detail="Frontend build not found in frontend/dist. Run `npm run build` in frontend/ or `./brotal`.",
        )
    if full_path:
        candidate = (FRONTEND_DIST / full_path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(FRONTEND_DIST.resolve())):
            return FileResponse(candidate)
    return FileResponse(index_file)
