# Brotal — Contrato Técnico `v0.1` (Cimientos para Co-Desarrollo)

> **Propósito:** Definir los contratos de datos, arquitectura de repositorio, esquema SQLite, endpoints FastAPI y reparto inicial de tareas para que **Yastin (Frontend React+TS + Arquitectura)** y **co-desarrollador (Backend Python+FastAPI)** puedan programar en paralelo sin bloquearse ni pisarse archivos.
> **Documentos del repo:** [README](../README.md) · [CONTRIBUTING](../CONTRIBUTING.md) · [Issues backend #2–#4](./ISSUES-2-3-4.md)

---

## 1. Arquitectura de Repositorios (GitHub Organization `brotal`)

Separación estricta entre el motor, el índice comunitario y los paquetes de cursos:

1. **`brotal/brotal-core` (Licencia: AGPLv3)** — El software local-first. **Cero apuntes ni ramos hardcodeados** (solo 1 fixture mínimo de prueba en `fixtures/`).
2. **`brotal/brotal-registry` (Licencia: CC-BY-SA / MIT para metadatos)** — Repositorio ultraliaviano con `registry.json` y los `CareerManifest` (~5 KB c/u) aportados vía Pull Request.
3. **`<usuario>/brotal-pack-<ramo>`** — Repositorios independientes de cada creador con su `CoursePack` (~300–500 KB, texto/JSON puro, **prohibido incluir PDFs/PPTX con copyright de terceros**).

### Estructura de carpetas de `brotal-core`
```text
brotal-core/
├── LICENSE                     # GNU AGPLv3
├── README.md                   # Instalación rápida + filosofía BYOK ($0)
├── CONTRIBUTING.md             # Flujo Issues -> Branch -> PR -> Review
├── .env.example                # Claves opcionales (GROQ_API_KEY, GEMINI_API_KEY, OLLAMA_URL)
├── backend/                    # Python 3.11+ · FastAPI · SQLite · Pydantic v2
│   ├── pyproject.toml          # Dependencias base livianas (sin PyTorch)
│   ├── app/
│   │   ├── main.py             # Entrypoint FastAPI + CORS + /openapi.json
│   │   ├── config.py           # Rutas locales (~/.brotal/) y lectura de keys
│   │   ├── db/
│   │   │   ├── database.py     # Conexión SQLite + inicialización de tablas
│   │   │   └── schema.sql      # DDL fuente de verdad (incluye FTS5)
│   │   ├── schemas/            # Modelos Pydantic (CareerManifest, CoursePack, Eval)
│   │   ├── routers/            # profile.py, registry.py, courses.py, study.py, chat.py
│   │   └── services/
│   │       ├── ai_router.py    # Pool gratuito multi-proveedor (Groq/Gemini/Ollama)
│   │       ├── pack_manager.py # Instalar, exportar y archivar Course Packs
│   │       ├── ingest.py       # Extracción local PDF/PPTX/DOCX/MD -> FTS5 -> árbol
│   │       ├── evaluator.py    # Rúbrica 7/10 + lógica de cooldown 0/3 -> 3/3
│   │       └── tts.py          # Síntesis edge-tts con caché en disco
│   └── tests/                  # pytest (contratos JSON, SQLite, lógica 3/3)
├── frontend/                   # Vite · React 18+ · TypeScript · Tailwind CSS
│   ├── package.json
│   └── src/
│       ├── api/                # Cliente HTTP + tipos generados desde /openapi.json
│       ├── store/              # Zustand (perfil, tema, ramo activo, modo malla)
│       ├── components/
│       │   ├── layout/         # TopBar ([Malla] | [v Ramo]), ThemeToggle, ChatDrawer
│       │   ├── curriculum/     # CurriculumGrid (S1..Sn), CourseCard, CourseModal
│       │   └── study/          # SkillTree (React Flow), StoryPlayer, EvalPanel
│       └── pages/              # OnboardingPage, CurriculumPage, CourseStudyPage
├── plugins/                    # Módulos opcionales aislados (instalación bajo demanda)
│   └── pronounce-ipa/          # Worker Wav2Vec2/PyTorch para idiomas (v1.2)
└── fixtures/                   # Datos de prueba para desarrollo local sin internet
    ├── demo_career.json
    └── demo_pack.json
```

---

## 2. Reglas de Diseño UI/UX Obligatorias (Desde `v0.1`)

- **Cero emojis en la interfaz:** Solo íconos SVG minimalistas (`lucide-react`, `stroke="currentColor"`) donde aporten función real.
- **Tema Claro / Oscuro** sincronizado globalmente (`localStorage.brotal_theme`).
- **Sin login ni cuentas en servidor:** Perfil 100 % local en SQLite.
- **Toggle de Malla en el header de `Mi Malla`:**
  - `Modo Carrera (Realista)`: Muestra avance de créditos/ramos y atenúa ramos cuyos prerrequisitos aún no están aprobados (con botones *"Marcar semestres anteriores aprobados"* y *"Abrir/estudiar igual"* — **nunca bloquea el acceso real al contenido**).
  - `Modo Libre`: Todos los ramos visibles a color completo y seleccionables en 1 clic, manteniendo igual los indicadores de estado (`Cursando` / `Aprobado`).
- **Barra superior de estudio (`Course Switcher`):** `[ ⌂ Malla ] | [ ▾ Ramo actual ]` listando **solo ramos en estado `active` (`Cursando`)** + atajo `Ctrl+K` + botón `+ Gestionar ramos / Ir a Malla`.

---

## 3. Contratos JSON Exactos (`schema_version: "1.0"`)

### 3.1 `CareerManifest` (Malla curricular — ~5 KB)
Vive en `brotal-registry/careers/<country>/<university>/<career_slug>.json`.

```json
{
  "schema_version": "1.0",
  "id": "cl-pucv-inf-2022",
  "country": "CL",
  "university": {
    "id": "pucv",
    "name": "Pontificia Universidad Católica de Valparaíso",
    "short_name": "PUCV"
  },
  "career": {
    "name": "Ingeniería en Informática",
    "plan_year": 2022,
    "plan_ref": "DRA 6/2022",
    "updated_at": "2026-11-24"
  },
  "categories": [
    { "id": "inf", "label": "Informática", "color": "#2E7D5B" },
    { "id": "mat", "label": "Matemáticas y Ciencias", "color": "#2B5B84" },
    { "id": "eng", "label": "Inglés", "color": "#8C6D1F" },
    { "id": "gen", "label": "Formación Fundamental", "color": "#8A335C" }
  ],
  "semesters": [
    {
      "number": 4,
      "label": "S4",
      "courses": [
        {
          "code": "INF2235",
          "name": "Base de Datos",
          "credits": 4,
          "category": "inf",
          "prerequisites": ["INF2240"]
        },
        {
          "code": "INF2236",
          "name": "Programación Avanzada",
          "credits": 4,
          "category": "inf",
          "prerequisites": ["INF2240"]
        },
        {
          "code": "INF2237",
          "name": "Ingeniería de Software",
          "credits": 4,
          "category": "inf",
          "prerequisites": ["INF2236"]
        },
        {
          "code": "INF2324",
          "name": "Redes Computacionales",
          "credits": 4,
          "category": "inf",
          "prerequisites": ["INF2236"]
        },
        {
          "code": "ING9001",
          "name": "Inglés 1",
          "credits": 2,
          "category": "eng",
          "prerequisites": [],
          "optional": false
        }
      ]
    }
  ]
}
```

> **Campos opcionales en `CareerManifest`:** `career.plan_ref` (ej. decreto o código oficial de plan, como `"DRA 6/2022"`) y `courses[].optional` (`boolean`, por defecto `false`, útil para ramos de Formación Fundamental o nivelación como `IER010` / `ING9000`).

### 3.2 `CoursePack` (`pack.json` — ~300–500 KB, sin PDFs con copyright)
Formato único tanto para **packs comunitarios descargados** como para **ramos generados en local** y **exportables**.

```json
{
  "schema_version": "1.0",
  "id": "cl-pucv-inf2324-ccna1",
  "course_code": "INF2324",
  "title": "Redes Computacionales · CCNA 1",
  "language": "es",
  "engine_type": "concept_tree",
  "metadata": {
    "university_id": "pucv",
    "career_ids": ["cl-pucv-inf-2022"],
    "created_year": 2024,
    "updated_year": 2026,
    "version": "1.0.0",
    "authors": ["ElFruutas"],
    "license": "CC-BY-SA-4.0",
    "world_metaphor": "Edificio NetTower (capas OSI como pisos del edificio)"
  },
  "nodes": [
    {
      "id": "B2-P3",
      "parent_ids": ["B2-P1"],
      "branch": "theory",
      "block": "Bloque 2 · Aplicación y Transporte",
      "title": "Correo (SMTP, POP3 vs IMAP) y Archivos (FTP vs TFTP)",
      "summary": "Qué problema resuelve cada protocolo de capa de aplicación y en qué se diferencian.",
      "story_script": "Texto conversado continuo (sin listas secas) con analogía espacial...",
      "eval_prompts": [
        {
          "id": "q1",
          "question": "Si lees tu correo desde el celular y el notebook y quieres que siga sincronizado, ¿qué protocolo usas y por qué no POP3?",
          "rubric_points": [
            "Identifica IMAP para sincronización en servidor",
            "Explica que POP3 descarga y suele borrar del servidor",
            "Distingue que SMTP es para envío, no lectura"
          ]
        }
      ],
      "storyboard_ref": null
    }
  ]
}
```

> **Nota de extensibilidad y semántica de `branch`:**
> - `branch` define a qué mitad del árbol bi-direccional pertenece el nodo: **`"theory"`** (copa superior de contenidos conceptuales) o **`"practice"`** (raíces inferiores de exámenes, talleres y laboratorios). Los nodos iniciales de la copa llevan `"branch": "theory"` con `"parent_ids": []`.
> - `engine_type` acepta `"concept_tree"` (`v0.1`/`v1.0`), `"code_lab"` (`v1.1+`) y `"language_studio"` (`v1.2+`). `storyboard_ref` permite enchufar animaciones sincronizadas en `v1.1` sin romper el esquema base.

### 3.3 `registry.json` (Índice comunitario liviano)
```json
{
  "schema_version": "1.0",
  "updated_at": "2026-11-24",
  "careers": [
    {
      "id": "cl-pucv-inf-2022",
      "country": "CL",
      "university": "PUCV",
      "career_name": "Ingeniería Informática",
      "plan_year": 2022,
      "manifest_url": "https://raw.githubusercontent.com/brotal/brotal-registry/main/careers/cl/pucv/inf-2022.json"
    }
  ],
  "packs": [
    {
      "id": "cl-pucv-inf2324-ccna1",
      "career_ids": ["cl-pucv-inf-2022"],
      "course_code": "INF2324",
      "title": "Redes Computacionales · CCNA 1",
      "engine_type": "concept_tree",
      "created_year": 2024,
      "updated_year": 2026,
      "version": "1.0.0",
      "pack_url": "https://raw.githubusercontent.com/ElFruutas/brotal-pack-redes-ccna1/main/pack.json"
    }
  ]
}
```

---

## 4. Esquema de Base de Datos Local (`SQLite` en `~/.brotal/brotal.db`)

Un único archivo local; cero dependencia de PostgreSQL o Docker. Incluye **retención espaciada honesta** (`0/3 → 3/3` con cooldown) separada de **entrenamiento** (`reps / best_score`).

```sql
-- 1. Perfil local (1 fila por instalación, sin login)
CREATE TABLE user_profile (
  id                INTEGER PRIMARY KEY CHECK (id = 1),
  display_name      TEXT NOT NULL DEFAULT 'Estudiante',
  career_id         TEXT,                         -- NULL si es autodidacta
  curriculum_mode   TEXT NOT NULL DEFAULT 'realistic' CHECK (curriculum_mode IN ('realistic', 'free')),
  cooldown_mode     TEXT NOT NULL DEFAULT 'semester'  CHECK (cooldown_mode IN ('semester', 'urgency')),
  theme             TEXT NOT NULL DEFAULT 'dark'      CHECK (theme IN ('dark', 'light')),
  ai_provider       TEXT NOT NULL DEFAULT 'auto', -- auto | groq | gemini | ollama
  created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Malla cargada localmente (caché del CareerManifest o malla propia)
CREATE TABLE installed_careers (
  id                TEXT PRIMARY KEY,
  manifest_json     TEXT NOT NULL,
  installed_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Ramos del usuario (conectados a malla o libres)
CREATE TABLE courses (
  id                TEXT PRIMARY KEY,             -- ej. "cl-pucv-inf2324-ccna1" o uuid local
  career_id         TEXT,                         -- NULL si es ramo libre
  course_code       TEXT,                         -- ej. "INF2324"
  title             TEXT NOT NULL,
  engine_type       TEXT NOT NULL DEFAULT 'concept_tree',
  status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'passed', 'archived')),
  source_type       TEXT NOT NULL DEFAULT 'local'   CHECK (source_type IN ('pack', 'local')),
  pack_version      TEXT,
  created_year      INTEGER,
  updated_year      INTEGER,
  pack_metadata_json TEXT,
  updated_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 4. Nodos del árbol de habilidades por ramo
CREATE TABLE course_nodes (
  id                TEXT NOT NULL,
  course_id         TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  parent_ids_json   TEXT NOT NULL DEFAULT '[]',
  branch            TEXT NOT NULL DEFAULT 'theory' CHECK (branch IN ('theory', 'practice')),
  block_label       TEXT,
  title             TEXT NOT NULL,
  summary           TEXT,
  story_script      TEXT,
  eval_prompts_json TEXT NOT NULL DEFAULT '[]',
  storyboard_json   TEXT,
  PRIMARY KEY (course_id, id)
);

-- 5. Progreso pedagógico honesto (Retención 0/3->3/3 vs Entrenamiento Reps/Best)
CREATE TABLE node_progress (
  course_id         TEXT NOT NULL,
  node_id           TEXT NOT NULL,
  mastery_level     INTEGER NOT NULL DEFAULT 0 CHECK (mastery_level BETWEEN 0 AND 3),
  next_review_at    TEXT,                         -- NULL si disponible para subir nivel
  training_reps     INTEGER NOT NULL DEFAULT 0,
  best_score        REAL NOT NULL DEFAULT 0,
  last_score        REAL,
  last_practiced_at TEXT,
  PRIMARY KEY (course_id, node_id),
  FOREIGN KEY (course_id, node_id) REFERENCES course_nodes(course_id, id) ON DELETE CASCADE
);

-- 6. Historial de intentos a ciegas (auditoría + futura analítica de patrones)
CREATE TABLE evaluation_attempts (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id         TEXT NOT NULL,
  node_id           TEXT NOT NULL,
  answers_json      TEXT NOT NULL,
  score             REAL NOT NULL,                -- 1.0 a 10.0
  passed            INTEGER NOT NULL,             -- 1 si score >= 7.0
  counted_mastery   INTEGER NOT NULL,             -- 1 si subió 0/3->3/3, 0 si fue entrenamiento en cooldown
  feedback_json     TEXT NOT NULL,
  created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 7. Memoria acotada del Chat Tutor transversal por ramo
CREATE TABLE chat_messages (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id         TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  node_id           TEXT,                         -- contexto de pantalla actual
  role              TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content           TEXT NOT NULL,
  created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 8. Índice local FTS5 de apuntes subidos por el usuario (BYOF, nunca sale del PC)
CREATE VIRTUAL TABLE local_chunks_fts USING fts5(
  course_id UNINDEXED,
  source_file,
  section_title,
  content
);
```

---

## 5. Contrato de API REST (`FastAPI` · Prefijo `/api/v1`)

> **Regla de sincronización Front ↔ Back:** FastAPI expone `/openapi.json`. El frontend corre `npx openapi-typescript` contra ese esquema para generar tipos TypeScript exactos — si cambia un campo en Python, TypeScript avisa al instante.

| Grupo | Método y Ruta | Propósito |
|---|---|---|
| **Perfil** | `GET /api/v1/profile` | Devuelve perfil local, tema, `curriculum_mode`, estado de API keys (sin exponer los secretos). |
| **Perfil** | `PATCH /api/v1/profile` | Actualiza nombre, carrera activa, `curriculum_mode` (`realistic` \| `free`), `cooldown_mode` y proveedor IA. |
| **Registry** | `GET /api/v1/registry` | Obtiene/cachea `registry.json` (lista de universidades, carreras y packs disponibles, con fallback offline). |
| **Malla** | `GET /api/v1/careers/{career_id}` | Devuelve el `CareerManifest` + estado local de cada ramo (`pending/active/passed/archived`) + progreso de créditos. |
| **Malla** | `POST /api/v1/careers/{career_id}/bulk-status` | Acción rápida: *"Marcar semestres 1..N como aprobados"* en 1 clic. |
| **Ramos** | `GET /api/v1/courses` | Lista ramos del usuario (filtro opcional `?status=active` para alimentar el `Course Switcher`). |
| **Ramos** | `POST /api/v1/courses/install-pack` | Instala un `CoursePack` desde URL o archivo `.json` local y lo marca `active`. |
| **Ramos** | `POST /api/v1/courses/ingest-local` | Sube PDFs/PPTX/MD locales → indexa en FTS5 → genera borrador de `CoursePack` con el router IA. |
| **Ramos** | `PATCH /api/v1/courses/{course_id}` | Cambia estado (`active`, `passed`, `archived` — al archivar borra caché TTS/chunks pesados conservando `node_progress`). |
| **Ramos** | `GET /api/v1/courses/{course_id}/export` | Exporta un `pack.json` limpio (sin archivos originales con copyright) listo para compartir en GitHub. |
| **Estudio** | `GET /api/v1/courses/{course_id}/tree` | Devuelve todos los nodos + `node_progress` (`mastery_level`, `next_review_at`, `training_reps`, `best_score`). |
| **Estudio** | `POST /api/v1/study/{course_id}/{node_id}/tts` | Genera o devuelve desde caché el audio MP3 de la historia (`edge-tts`). |
| **Estudio** | `POST /api/v1/study/{course_id}/{node_id}/evaluate` | Evalúa respuestas a ciegas en orden mezclado (nota `1..10`, aprueba `≥ 7.0`, aplica regla de cooldown `0/3 → 3/3` vs `Reps`). |
| **Tutor** | `POST /api/v1/chat/{course_id}` | Chat tutor transversal consciente del `node_id` actual y memoria acotada del ramo. |

---

## 6. Corte de Alcance y Primer Reparto de Issues (`v0.1` → `v1.0`)

### Qué entra en `v0.1` (Cimientos — ~1 semana relajada)
Solo el esqueleto funcionando de punta a punta con `fixtures/demo_career.json` y `fixtures/demo_pack.json`, **antes** de meter IA compleja ni ingesta de PDFs:
- Onboarding de Perfil Local + Vista `Mi Malla` (con toggle `Modo Carrera` / `Modo Libre` y modal de ramo).
- `Course Switcher` (`[ ⌂ Malla ] | [ ▾ Ramo ]`) mostrando solo ramos `active`.
- Árbol del ramo en React Flow leyendo nodos reales desde FastAPI + SQLite.
- Evaluación simulada/conectada a 1 proveedor IA y actualización real de `node_progress` (`0/3 → 3/3` y `Reps`).

### Qué completa `v1.0` (MVP Público)
- Router multi-IA gratuito real (`Groq`, `Gemini Free`, `Ollama`) + pantalla de configuración de API keys.
- Ingesta local BYOF (`PDF/PPTX/MD` → FTS5 → generación de árbol inicial).
- `tts.py` (`edge-tts` con caché) + Chat Tutor transversal por ramo.
- Instalar/Exportar `CoursePack` conectado al `brotal-registry` real (con los primeros 1–2 packs reales de Yastin).
- *(Todo lo demás — animaciones sincronizadas tipo video, escenario clickeable "Plop! Error", módulo acústico IPA `Wav2Vec2`, fusión híbrida Pack+PDFs y Tauri 1-clic — entra ordenadamente en `v1.1` y `v1.2`).*

### Primer Backlog de Issues para Co-Desarrollo (Sin pisarse)

| Issue | Responsable sugerido | Entregable verificable (Criterio de Aceptación) |
|---|---|---|
| `#1` Setup Monorepo + `LICENSE` (AGPLv3) + `fixtures/` | **Yastin** | Repo `brotal/brotal-core` creado con carpetas, `.gitignore`, `.env.example`, `demo_career.json` y `demo_pack.json` válidos. |
| `#2` Backend Base: FastAPI + `schema.sql` + SQLite + `/profile` | **Amigo (Python)** | `uvicorn app.main:app` levanta limpio, crea `brotal.db` con las 8 tablas, `GET/PATCH /api/v1/profile` pasa tests en `pytest`. |
| `#3` Backend Malla & Packs: `/careers`, `/courses`, `pack_manager.py` | **Amigo (Python)** | Carga `demo_career.json`, instala `demo_pack.json`, soporta `bulk-status`, `archive` y `export` limpio sin archivos privados. |
| `#4` Backend Estudio: `evaluator.py` (lógica `7/10` + cooldown `0/3→3/3` vs `Reps`) | **Amigo (Python)** | Tests unitarios verificando que aprobar en cooldown suma `training_reps` pero NO infla `mastery_level`, y fuera de cooldown sí sube nivel. |
| `#5` Frontend Base: Vite+React+TS+Tailwind + cliente OpenAPI + Tema + TopBar | **Yastin (Front)** | App levanta en `localhost:5173`, cero emojis (solo `lucide-react`), Tema Claro/Oscuro y `[ ⌂ Malla ] | [ ▾ Ramo ]` funcionando. |
| `#6` Frontend `Mi Malla`: Columnas `S1..Sn` + Toggle `Modo Carrera / Libre` + Modal | **Yastin (Front)** | Renderiza `demo_career.json` con colores por área, barra de progreso/créditos, toggle realista/libre, botón *"Marcar semestres anteriores"* y modal de ramo. |
| `#7` Frontend Árbol + Evaluación `7/10`: React Flow + Panel de Estudio | **Yastin (Front)** | Muestra nodos del pack con estados `0/3..3/3` + `Reps`, permite leer historia, responder a ciegas y ver feedback real del backend. |
