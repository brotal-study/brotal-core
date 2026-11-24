# Issues backend `v0.1` (para subir a GitHub)

Contexto común: leer `README.md`, `CONTRIBUTING.md`, `fixtures/`, `backend/app/db/schema.sql` y [`docs/CONTRATO-V0.1.md`](./CONTRATO-V0.1.md). Los stubs en `backend/app/` ya declaran el contrato en sus docstrings. Etiquetas sugeridas: `backend`, `v0.1`.

---

## Issue #2 — Backend base: FastAPI + SQLite + `/profile`

**Descripción.** Dejar el backend arrancando de punta a punta: configuración de rutas locales, inicialización idempotente de SQLite con las 8 tablas y los endpoints de perfil local (sin login).

**Archivos a tocar**
- `backend/app/config.py` (`BROTAL_HOME`, default `~/.brotal`; `db_path()`; `configured_providers()` que solo devuelve bool por proveedor, nunca la key).
- `backend/app/db/database.py` (`init_db()` ejecuta `schema.sql` y crea la fila `user_profile` con `id=1`; `get_conn()` como dependencia con `foreign_keys=ON` y `row_factory=sqlite3.Row`).
- `backend/app/schemas/profile.py` (nuevo: `Profile`, `ProfilePatch`).
- `backend/app/routers/profile.py` (nuevo).
- `backend/app/main.py` (llamar `init_db()` al iniciar con `lifespan`; incluir router con prefijo `/api/v1`).
- `backend/tests/test_profile.py` (nuevo; usar `BROTAL_HOME` temporal vía fixture de pytest).

**Criterios de aceptación**
- [ ] `uvicorn app.main:app` levanta limpio y crea `brotal.db` con las 8 tablas (incluida `local_chunks_fts`).
- [ ] `GET /api/v1/profile` devuelve perfil, tema, `curriculum_mode`, `cooldown_mode`, `ai_provider` y `providers: {groq, gemini, ollama}` como booleanos, sin exponer secretos.
- [ ] `PATCH /api/v1/profile` actualiza `display_name`, `career_id`, `curriculum_mode` (`realistic|free`), `cooldown_mode` (`semester|urgency`), `theme` y `ai_provider`; valores inválidos devuelven 422.
- [ ] Reiniciar el servidor no duplica ni pierde datos (idempotente).
- [ ] `pytest` verde y los tests no tocan el `~/.brotal` real.
- [ ] `/openapi.json` refleja los modelos (lo consumirá el frontend con `openapi-typescript`).

---

## Issue #3 — Backend malla y packs: `/careers`, `/courses`, `pack_manager.py`

**Descripción.** Cargar una malla (`CareerManifest`), instalar un `CoursePack`, y soportar acciones masivas, archivado y exportación limpia.

**Archivos a tocar**
- `backend/app/schemas/career.py` y `backend/app/schemas/pack.py` (nuevos; modelos Pydantic v2 que validan `fixtures/demo_career.json` y `fixtures/demo_pack.json`, con `schema_version == "1.0"`). Nota: el manifest admite el campo opcional `optional: true` en ramos y `plan_ref` en `career`.
- `backend/app/services/pack_manager.py` (`install_pack`, `archive_course`, `export_pack`, `bulk_status`).
- `backend/app/routers/courses.py` (nuevo) y `backend/app/routers/registry.py` (nuevo, con caché local y fallback offline que lea `fixtures/`).
- `backend/app/main.py` (registrar routers).
- `backend/tests/test_careers.py`, `test_pack_manager.py` (nuevos).

**Endpoints (prefijo `/api/v1`)**: `GET /registry`, `GET /careers/{career_id}`, `POST /careers/{career_id}/bulk-status`, `GET /courses` (`?status=`), `POST /courses/install-pack`, `PATCH /courses/{course_id}`, `GET /courses/{course_id}/export`.

**Criterios de aceptación**
- [ ] Cargar `demo_career.json` y `GET /careers/cl-pucv-inf-2022` devuelve el manifest más el estado local de cada ramo (`pending|active|passed|archived`) y créditos aprobados / totales.
- [ ] `POST /courses/install-pack` con `demo_pack.json` (cuerpo JSON o URL) crea el curso en `active` con sus nodos y `node_progress` en `mastery_level = 0`; instalar dos veces no duplica.
- [ ] `bulk-status` marca S1..N como `passed` en una sola llamada y devuelve cuántos ramos cambió.
- [ ] `PATCH` a `archived` borra caché TTS y chunks FTS del ramo, pero conserva `node_progress` y `evaluation_attempts`.
- [ ] `export` devuelve un `pack.json` válido contra el esquema, sin rutas locales ni archivos originales; exportar y reinstalar da el mismo árbol.
- [ ] Pack con `schema_version` distinta o campos faltantes devuelve 422 con mensaje claro.
- [ ] `pytest` verde.

---

## Issue #4 — Backend estudio: `evaluator.py` (`7/10` + cooldown `0/3 → 3/3` vs `Reps`)

**Descripción.** Implementar la lógica pedagógica central como funciones puras testeables, y exponer el árbol y la evaluación. La evaluación puede usar un puntaje inyectado o simulado en `v0.1`; la integración con IA real es de `v1.0`.

**Archivos a tocar**
- `backend/app/services/evaluator.py` (`apply_evaluation`, ver reglas en el docstring).
- `backend/app/schemas/study.py` (nuevo: `NodeProgress`, `EvaluateRequest`, `EvaluateResponse`).
- `backend/app/routers/study.py` (nuevo).
- `backend/tests/test_evaluator.py` (nuevo; sin reloj real: inyectar `now`).

**Endpoints**: `GET /api/v1/courses/{course_id}/tree` (nodos + `mastery_level`, `next_review_at`, `training_reps`, `best_score`) y `POST /api/v1/study/{course_id}/{node_id}/evaluate` (`answers` en el orden recibido; devuelve `score` 1..10, `passed`, `counted_mastery`, `feedback`, progreso actualizado).

**Criterios de aceptación**
- [ ] `passed` es verdadero solo si `score >= 7.0`.
- [ ] Aprobar sin cooldown activo sube `mastery_level` en 1 (máximo 3), fija `next_review_at` según `cooldown_mode` y guarda `counted_mastery = 1`.
- [ ] Aprobar con cooldown activo suma `training_reps`, NO cambia `mastery_level` y guarda `counted_mastery = 0`.
- [ ] Reprobar nunca baja `mastery_level`; actualiza `last_score` y `best_score = max(...)`.
- [ ] Cada evaluación inserta una fila en `evaluation_attempts`.
- [ ] Tests unitarios cubren: límite 7.0 exacto, tope 3/3, cooldown activo y vencido, ambos `cooldown_mode`.
- [ ] `GET /tree` sobre el pack demo devuelve los 4 nodos con progreso inicial `0/3`.
- [ ] `pytest` verde.
