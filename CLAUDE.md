# CLAUDE.md — Guía para Agentes IA y Colaboradores (`brotal-core v1.1.2`)

Este documento es la **fuente única de verdad** para agentes de programación (Claude Code, Antigravity, Cursor, Codex) y colaboradores humanos. Léelo completo antes de proponer o escribir cambios.

---

## 1. Qué es Brotal y qué NO es

### Qué ES
- **Motor open-source ([AGPLv3](LICENSE)) y local-first** de estudio activo universitario y técnico.
- **Sin login ni cuentas (`Perfil Local`):** todo el progreso vive localmente en SQLite (`~/.brotal/brotal.db`).
- **Costo `$0` (BYOK — Bring Your Own Key):** rotación automática entre proveedores gratuitos (**Groq**, **Gemini Free**) y **Ollama local** (`http://127.0.0.1:11434`), con claves guardadas en `~/.brotal/.env` (`0600`) fuera del repo.
- **Aprendizaje activo y evaluación a ciegas:** transforma apuntes propios en árboles de habilidades con dominio progresivo (`0/3 -> 3/3`), exigiendo nota `>= 7/10` sin acceso al apunte durante la evaluación y separando retención espaciada (`0/3 -> 3/3`) de práctica repetida (`training_reps`).

### Qué NO es (límites de diseño)
- **NO es un resolutor automático de tareas o exámenes:** la IA actúa como arquitecto de ruta, tutor socrático y evaluador a ciegas (*Senior Dev* en código), nunca para hacerle la tarea al estudiante.
- **NO es un SaaS ni tiene telemetría/auth:** prohibido agregar registro de usuarios, pasarelas de pago, trackers o servidores centrales obligatorios.
- **NO es un lector pasivo de resúmenes:** la teoría siempre desemboca en evaluación activa (`branch: "theory" | "practice"` y `challenge_type: "concept" | "trace" | "debug" | "implement"`).

---

## 2. Arquitectura Real (`v1.1.2`)

```text
brotal                      # Launcher bash en 1 comando (producción, --dev, --check)
backend/
  app/
    main.py                 # FastAPI + montaje de SPA estática (no-cache en index.html) y /api/v1/*
    config.py               # Gestión de ~/.brotal/, .env (0600) y variables de entorno
    db/
      schema.sql            # DDL SQLite + FTS5 (local_chunks_fts) + exam_routes + evaluation_attempts
      database.py           # Conexión SQLite + inicialización y migraciones idempotentes
    schemas/                # Contratos Pydantic v2: career.py, pack.py, study.py, profile.py
    routers/                # profile.py, registry.py, courses.py, study.py, chat.py, settings.py
    services/
      ai_router.py          # Pool multi-IA (Groq / Gemini / Ollama) + evaluación + Code Lab + rutas de examen
      ingest.py             # Ingesta local BYOF (.pdf, .pptx, .docx, .md, .txt) sin PyTorch -> FTS5 + árbol IA
      tts.py                # Voz neural edge-tts con caché SHA-256 en disco + timestamps palabra por palabra
      evaluator.py          # Reglas deterministas de aprobación (>= 7.0), cooldown y transición 0/3 -> 3/3
      pack_manager.py       # Instalación de CoursePack e ingesta incremental (append/replace)
  tests/                    # Suite pytest de contratos, flujo de estudio, ingesta, TTS, Code Lab y rutas
frontend/
  src/
    api/                    # client.ts, curriculum.ts, study.ts, types.ts contra /api/v1/*
    store/                  # useAppStore.ts y useStudyStore.ts (Zustand + localStorage.brotal_theme)
    pages/                  # OnboardingPage.tsx, CurriculumPage.tsx, CourseStudyPage.tsx
    components/
      layout/               # TopBar.tsx, CommandPalette.tsx, AiSettingsModal.tsx, ChatDrawer.tsx, ThemeToggle.tsx
      curriculum/           # CourseCard.tsx, CourseModal.tsx
      study/                # SkillTree.tsx (@xyflow/react), SkillNode.tsx, StudyStation.tsx, StoryTab.tsx, EvalTab.tsx, CodeChallengeInput.tsx (CodeMirror), ExamRouteModal.tsx, CourseFilesPanel.tsx, IngestModal.tsx
fixtures/                   # demo_career.json (CareerManifest) y demo_pack.json (CoursePack)
scripts/validate_fixtures.py# Validador oficial de fixtures contra el contrato
```

---

## 3. Reglas No Negociables

1. **Cero emojis en `frontend/src`:** usa exclusivamente íconos SVG de `lucide-react`. El CI falla si detecta cualquier carácter emoji Unicode en `frontend/src`.
2. **Tema Claro y Oscuro obligatorio:** todo componente nuevo debe verse con contraste limpio en ambos modos usando clases Tailwind (`dark:...`, activado mediante clase `.dark` en `<html>` vía `localStorage.brotal_theme`).
3. **Geometría del Árbol de Habilidades (`SkillTree.tsx` / `SkillNode.tsx`):**
   - Los nodos son **tarjetas rectangulares** legibles con título completo, tipo y barra de maestría `0/3 -> 3/3` (nunca medallones circulares con texto truncado).
   - La copa del árbol (`theory`) se organiza en **columnas paralelas por bloque temático** saliendo desde el núcleo central (y `practice` abajo), nunca en una sola fila o torre infinita.
4. **Liviano y sin dependencias pesadas:** prohibido introducir PyTorch, TensorFlow, CUDA, modelos locales pesados en RAM o Docker obligatorio. Brotal debe correr en laptops estudiantiles modestas con `./brotal`.
5. **Privacidad y copyright absolutos:** cero nombres o datos personales, cero claves reales en el código/tests y cero archivos `.pdf`, `.pptx` o `.docx` con copyright en el repositorio.
6. **SQLite siempre idempotente:** toda tabla o índice nuevo en `backend/app/db/schema.sql` debe usar `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`, y cualquier columna nueva en tablas existentes debe migrarse de forma segura e idempotente en `backend/app/db/database.py`.
7. **Retrocompatibilidad estricta de schemas Pydantic:** no rompas campos existentes en `EvalPrompt`, `CoursePack`, `CareerManifest` ni respuestas de `/api/v1/*`. Todo campo nuevo debe tener valor por defecto seguro (`default` o `Optional`) para no invalidar packs ni bases SQLite de versiones previas.

---

## 4. Qué Requiere Issue Aprobado Antes de Implementar

No abras un PR directo para cambios estructurales sin antes proponerlo en un Issue y recibir aprobación del mantenedor:
- Nuevas tablas en SQLite o nuevos endpoints HTTP en `/api/v1/*`.
- Nuevas dependencias en `backend/pyproject.toml` (`pip`) o `frontend/package.json` (`npm`).
- Cambios en la navegación principal, layout global o estructura de vistas.
- Nuevos motores o modos de estudio (ej. `problem_solver`, `language_studio`, plugins nuevos).

---

## 5. Flujo de Trabajo y Checklist Obligatorio antes de cada PR

1. **Rama dedicada desde `main`:** `git switch main && git pull && git switch -c <tipo>/<issue>-<slug>` (`feat`, `fix`, `docs`, `test`, `chore`).
2. **PR pequeño y atómico:** 1 Issue = 1 Pull Request. Evita mezclar refactorizaciones cosméticas con cambios funcionales.
3. **Ejecuta y verifica los 5 chequeos obligatorios en local antes de abrir el PR:**

```bash
# 1. Tests y linter de backend
cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app tests

# 2. Validación de contratos Pydantic contra fixtures
python3 scripts/validate_fixtures.py

# 3. Typecheck (tsc -b) y build de producción del frontend
cd frontend && npm run build

# 4. Verificación de cero emojis en frontend/src
python3 -c "import pathlib,re,sys; p=re.compile(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]'); hits=[f'{f}:{i}' for f in pathlib.Path('frontend/src').rglob('*') if f.is_file() for i,l in enumerate(f.read_text().splitlines(),1) if p.search(l)]; sys.exit('\n'.join(hits)) if hits else print('OK: 0 emojis')"

# 5. Smoke test integral del launcher
BROTAL_PORT=8009 ./brotal --check
```
