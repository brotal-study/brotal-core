-- Brotal schema v0.1 (fuente de verdad del DDL). Ver CONTRATO-V0.1 seccion 4.
PRAGMA foreign_keys = ON;

-- 1. Perfil local (1 fila por instalación, sin login)
CREATE TABLE IF NOT EXISTS user_profile (
  id                INTEGER PRIMARY KEY CHECK (id = 1),
  display_name      TEXT NOT NULL DEFAULT 'Estudiante',
  career_id         TEXT,                         -- NULL si es autodidacta
  curriculum_mode   TEXT NOT NULL DEFAULT 'realistic' CHECK (curriculum_mode IN ('realistic', 'free')),
  cooldown_mode     TEXT NOT NULL DEFAULT 'semester'  CHECK (cooldown_mode IN ('semester', 'urgency')),
  theme             TEXT NOT NULL DEFAULT 'dark'      CHECK (theme IN ('dark', 'light')),
  ai_provider       TEXT NOT NULL DEFAULT 'auto', -- auto | groq | gemini | ollama
  explanation_style TEXT NOT NULL DEFAULT 'narrative' CHECK (explanation_style IN ('narrative', 'direct', 'structured')),
  question_style    TEXT NOT NULL DEFAULT 'direct'    CHECK (question_style IN ('direct', 'scenario')),
  created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Malla cargada localmente (caché del CareerManifest o malla propia)
CREATE TABLE IF NOT EXISTS installed_careers (
  id                TEXT PRIMARY KEY,
  manifest_json     TEXT NOT NULL,
  installed_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Ramos del usuario (conectados a malla o libres)
CREATE TABLE IF NOT EXISTS courses (
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
CREATE TABLE IF NOT EXISTS course_nodes (
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
CREATE TABLE IF NOT EXISTS node_progress (
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
CREATE TABLE IF NOT EXISTS evaluation_attempts (
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
CREATE TABLE IF NOT EXISTS chat_messages (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id         TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  node_id           TEXT,                         -- contexto de pantalla actual
  role              TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content           TEXT NOT NULL,
  created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 8. Índice local FTS5 de apuntes subidos por el usuario (BYOF, nunca sale del PC)
CREATE VIRTUAL TABLE IF NOT EXISTS local_chunks_fts USING fts5(
  course_id UNINDEXED,
  source_file,
  section_title,
  content
);
