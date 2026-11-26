# Brotal (`v1.1.2`)

Motor open-source y local-first de estudio activo: convierte tus apuntes en árboles de habilidades (`0/3 -> 3/3`) con evaluación socrática a ciegas (aprobación `>= 7/10`), laboratorio de código interactivo (*Code Lab*), planificador de rutas de examen con detección de vacíos, voz neural sincronizada palabra por palabra y chat tutor transversal.

## ¿Por qué existe Brotal?

Hoy casi todos los estudiantes usamos la IA como un chat pasivo que resume PDFs o directamente nos resuelve la tarea. Eso genera una peligrosa **ilusión de competencia**: al leer la respuesta de la IA todo parece claro, pero frente a la hoja en blanco del examen no sabemos por dónde empezar.

**Brotal invierte el rol de la IA:** en lugar de responder por ti, toma tus propios apuntes, diseña un árbol de habilidades progresivo y actúa como un **examinador a ciegas y tutor socrático**. No desbloqueas el siguiente concepto hasta demostrar dominio real (`>= 7/10` sin mirar el apunte y superando 3 rondas de retención `0/3 -> 3/3`). Todo corriendo en tu propia máquina (**local-first**, sin cuentas ni servidores externos) y con **costo `$0` (BYOK)** para cualquier estudiante.

## Capacidades principales (`v1.1.2`)

- **Local-first y sin login:** todo tu progreso, historial de intentos y árboles viven localmente en SQLite (`~/.brotal/brotal.db`).
- **BYOK, costo `$0`:** pool multi-IA gratuito con rotación y fallback automático entre **Groq** (`llama-3.3-70b-versatile` / `openai/gpt-oss-120b`), **Gemini Free** (`gemini-2.5-flash`) y **Ollama local** (`http://127.0.0.1:11434`). Configura tus claves desde el ícono de engranaje en la barra superior (`~/.brotal/.env` con permisos `0600`, fuera del repositorio).
- **Ingesta local BYOF e incremental (`append` / `replace`, sin PyTorch):** sube tus propios `.pdf`, `.pptx`, `.docx`, `.md` o `.txt` para indexarlos en SQLite FTS5 y generar o expandir árboles de habilidades por unidad sin perder tu progreso previo.
- **Code Lab interactivo:** editor integrado con CodeMirror (`Java`, `SQL`, `Python`, `C`), detección automática del tipo de ramo, retos prácticos (`debug`, `trace`, `implement`) y evaluación a ciegas con rúbrica de *Senior Dev* (sin entregar esqueletos resueltos en retos básicos de implementación).
- **Ruta de examen IA:** ingresa la fecha de tu certamen/examen, horas disponibles y temario oficial; Brotal cruza el temario contra los nodos de tu árbol, detecta **vacíos de contenido** y arma un cronograma día a día priorizando nodos pendientes o en riesgo.
- **Voz neural (`edge-tts`) palabra por palabra:** lectura fluida con caché SHA-256 en disco, resaltado sincronizado sin saltos de layout, cancelación limpia y progreso porcentual compacto.
- **Chat Tutor con Markdown y navegación:** tutor contextual anclado al ramo que cita tus apuntes indexados (FTS5), renderiza Markdown/código, permite preguntar directo desde la explicación/evaluación y navegar a los nodos del árbol.
- **Malla curricular (`CareerManifest`) y Modo Libre:** seguimiento por malla universitaria en JSON (incluye demo PUCV y soporta aportes de nuevas universidades/institutos) o tablero libre para agregar cualquier ramo manualmente.
- **Licencia:** [AGPLv3](LICENSE).

## Arranque en 1 comando

```bash
./brotal           # Producción local: compila frontend si falta, levanta FastAPI en :8000 y abre el navegador
./brotal --dev     # Desarrollo: levanta FastAPI (:8000) + Vite (:5173) con hot-reload
./brotal --check   # Verificación rápida: comprueba /health, / y /api/v1/profile (HTTP 200)
```

## Estructura del proyecto

```text
brotal      Launcher en 1 comando (producción, --dev y --check)
backend/    Python 3.11+ · FastAPI · SQLite (FTS5) · Pydantic v2 · edge-tts · pypdf/pptx/docx
frontend/   Vite · React · TypeScript · Tailwind · @xyflow/react · CodeMirror · lucide-react · zustand
plugins/    Módulos opcionales (p. ej. pronounce-ipa, v1.2+)
fixtures/   demo_career.json (CareerManifest) y demo_pack.json (CoursePack)
scripts/    validate_fixtures.py
docs/       Contrato técnico y notas de arquitectura
```

## Desarrollo manual y tests

Backend:

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload      # http://localhost:8000/health
pytest -q && ruff check app tests
```

Frontend:

```bash
cd frontend
npm install
npm run dev                         # http://localhost:5173
npm run build
```

Validar contratos y fixtures: `python3 scripts/validate_fixtures.py`

## Probar y contribuir

Brotal está abierto tanto a **estudiantes testers** de cualquier universidad o instituto técnico como a **desarrolladores** (incluyendo quienes programan asistidos por Claude Code, Cursor o Antigravity):

- **¿Quieres probar Brotal con tus propios ramos o reportar un bug/mejora UX?** Abre un reporte usando nuestras plantillas en [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) ([Reporte de Bug](.github/ISSUE_TEMPLATE/bug_report.md) o [Idea / Mejora](.github/ISSUE_TEMPLATE/feature_idea.md)).
- **¿Quieres aportar código o una malla (`CareerManifest`) de tu carrera?** Revisa el flujo **Issue -> Fork -> Branch -> PR** en [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **¿Usas agentes de IA para programar?** Asegúrate de que tu agente lea [`CLAUDE.md`](CLAUDE.md) (y [`AGENTS.md`](AGENTS.md)) antes de tocar el repositorio.

## Reglas permanentes de UI, privacidad y copyright

- **Cero emojis en la interfaz (`frontend/src`):** solo íconos SVG de `lucide-react`.
- **Tema Claro/Oscuro** siempre soportado (`localStorage.brotal_theme`).
- **Sin login ni cuentas:** Perfil Local en SQLite.
- **Privacidad y copyright:** nunca subas al repositorio notas personales, nombres de terceros, claves reales ni archivos `.pdf`/`.pptx`/`.docx` con copyright.
