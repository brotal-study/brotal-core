"""Entrypoint FastAPI de Brotal. Los routers se registran aqui (Issues #2-#4)."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Brotal API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


# TODO(#2): app.include_router(profile.router, prefix="/api/v1")
# TODO(#3): app.include_router(registry/careers/courses routers, prefix="/api/v1")
# TODO(#4): app.include_router(study.router, prefix="/api/v1")
