# Contribuir a Brotal

Gracias por sumarte a **Brotal**. La rama `main` está protegida: ningún cambio entra sin pasar por nuestro flujo estándar y las validaciones automáticas de CI.

Flujo único de colaboración:
**Issue primero -> Fork -> Branch -> Checks verdes -> Pull Request -> Revisión del mantenedor**

---

## 3 Puertas de Entrada para Colaborar

1. **Estudiante Tester (Bugs y mejoras de UX):**
   - Prueba Brotal con tus propios apuntes (`.pdf`, `.pptx`, `.docx`, `.md`, `.txt`) en cualquier carrera universitaria o técnica.
   - Reporta errores o fricciones reales de estudio usando las plantillas en [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/).
2. **Aportar una Malla Curricular (`CareerManifest`) anonimizada:**
   - Puedes exportar o armar el JSON de una carrera de tu universidad o instituto técnico respetando el schema `CareerManifest` (`backend/app/schemas/career.py`).
   - Debe contener únicamente estructura curricular pública (códigos, nombres de asignaturas, semestres y prerrequisitos), sin datos personales ni material con copyright, y validar con `python3 scripts/validate_fixtures.py`.
3. **Desarrollo Backend / Frontend (`v1.2+`):**
   - Toma un Issue abierto (o propón uno nuevo antes de programar) para mejoras del motor en `backend/` (FastAPI, SQLite FTS5, `ai_router`, `ingest`, `tts`) o `frontend/` (React, TypeScript, Tailwind, `@xyflow/react`, CodeMirror).

---

## Flujo Paso a Paso

### 1. Issue primero
Toda tarea o cambio estructural parte de un Issue aprobado con descripción del problema, archivos involucrados y criterios de aceptación. Comenta en el Issue que lo tomas para evitar trabajo duplicado.

### 2. Fork y Branch
Crea un Fork del repositorio, clónalo y abre una rama descriptiva desde `main` actualizado:

```bash
git switch main && git pull
git switch -c <tipo>/<issue>-<descripcion-corta>   # ej. feat/42-export-exam-route
```

Tipos válidos: `feat`, `fix`, `docs`, `test`, `chore`. **Nunca hagas push directo a `main`.**

### 3. Uso de asistentes IA (Claude Code / Cursor / Antigravity)
Celebramos el desarrollo asistido por agentes de IA, pero con disciplina de ingeniería:
- **Lectura obligatoria de [`CLAUDE.md`](CLAUDE.md):** asegúrate de que tu agente cargue `CLAUDE.md` (y `AGENTS.md`) al iniciar la sesión. Ahí están la arquitectura real de `v1.1.2` y los guardrails que no pueden romperse.
- **PRs pequeños y atómicos:** 1 Issue = 1 Pull Request. No envíes PRs masivos generados a ciegas que mezclen múltiples temas o dependencias no aprobadas.
- **Responsabilidad humana:** tú eres responsable de entender, revisar y probar en tu máquina cada línea de código que tu agente escriba antes de abrir el PR.

### 4. Checks verdes obligatorios antes del PR
Antes de subir tu rama, ejecuta todos los chequeos locales (los mismos que correrá GitHub Actions en tu PR):

```bash
# 1. Backend: tests + linter
cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app tests

# 2. Contratos Pydantic y fixtures
python3 scripts/validate_fixtures.py

# 3. Frontend: typecheck + build
cd frontend && npm run build

# 4. Cero emojis en frontend/src
python3 -c "import pathlib,re,sys; p=re.compile(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]'); hits=[f'{f}:{i}' for f in pathlib.Path('frontend/src').rglob('*') if f.is_file() for i,l in enumerate(f.read_text().splitlines(),1) if p.search(l)]; sys.exit('\n'.join(hits)) if hits else print('OK: 0 emojis')"

# 5. Smoke test del launcher
BROTAL_PORT=8009 ./brotal --check
```

### 5. Pull Request y Revisión
- Abre el Pull Request hacia `main` completando la plantilla [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) y vinculando el Issue (`Closes #N`).
- Si tocas un contrato SQL o Pydantic, garantiza idempotencia en SQLite (`CREATE TABLE IF NOT EXISTS` / migración segura en `database.py`) y retrocompatibilidad en `backend/app/schemas/`.
- Todo PR requiere que el CI esté en verde y la aprobación del mantenedor antes de integrarse (*squash and merge*).

---

## Reglas No Negociables y Licencia

- **Cero emojis en `frontend/src`:** usa exclusivamente íconos SVG de `lucide-react`.
- **Tema Claro y Oscuro siempre soportados** y **sin login/cuentas** (`Perfil Local`).
- **Sin dependencias pesadas:** prohibido agregar PyTorch, CUDA o Docker obligatorio.
- **Privacidad y copyright:** cero claves reales (solo `.env.example`), cero nombres o notas personales y cero archivos `.pdf`/`.pptx`/`.docx` con copyright en el repositorio.
- **Licencia:** al enviar un Pull Request aceptas que tus aportes se distribuyan bajo la licencia [AGPLv3](LICENSE).
