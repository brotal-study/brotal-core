# Brotal (`v1.0`)

Motor open-source y local-first de estudio activo: convierte apuntes en árboles de habilidades (`0/3 → 3/3`) con evaluación socrática a ciegas (aprobación `>= 7/10`), voz neural con caché en disco, chat tutor transversal y paquetes comunitarios de ramos (*Course Packs*).

- **Local-first y sin login:** perfil local en SQLite (`~/.brotal/brotal.db`).
- **BYOK, costo `$0`:** pool multi-IA gratuito con rotación automática entre **Groq** (`llama-3.3-70b-versatile` / `openai/gpt-oss-120b`), **Gemini Free** (`gemini-2.5-flash`) y **Ollama local** (`http://127.0.0.1:11434`). Configura tus claves desde el ícono de engranaje en la barra superior (se guardan en `~/.brotal/.env` con permisos `0600`, fuera del repositorio).
- **Ingesta local BYOF (sin PyTorch):** sube tus propios `.pdf`, `.pptx`, `.docx`, `.md` o `.txt` para indexarlos en SQLite FTS5 y generar al instante un árbol de 6 a 12 nodos (`theory` + `practice`).
- **Cero contenido de ramos en el motor:** solo `fixtures/` con datos de prueba. Los Course Packs viven en repos aparte y nunca incluyen archivos originales con copyright.
- **Licencia:** [AGPLv3](LICENSE).

## Arranque en 1 comando

```bash
./brotal           # Producción local: compila frontend si falta, levanta FastAPI en :8000 y abre el navegador
./brotal --dev     # Desarrollo: levanta FastAPI (:8000) + Vite (:5173) con hot-reload
./brotal --check   # Verificación rápida: comprueba /health, / y /api/v1/profile (HTTP 200)
```

## Estructura

```text
brotal      Launcher en 1 comando (producción, --dev y --check)
backend/    Python 3.11+ · FastAPI · SQLite (FTS5) · Pydantic v2 · edge-tts · pypdf/pptx/docx
frontend/   Vite · React · TypeScript · Tailwind · lucide-react · zustand
plugins/    Módulos opcionales (p. ej. pronounce-ipa, v1.2)
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
pytest
```

Frontend:

```bash
cd frontend
npm install
npm run dev                         # http://localhost:5173
npm run build
```

Validar fixtures: `python3 scripts/validate_fixtures.py`

## Reglas de UI (permanentes)

- Cero emojis en la interfaz: solo íconos SVG de `lucide-react`.
- Tema Claro/Oscuro (`localStorage.brotal_theme`).
- Sin login ni cuentas: Perfil Local.

## Privacidad y copyright

No subas notas personales, claves reales, ni PDFs/PPTX/DOCX de terceros (profesores, editoriales). Los Course Packs exportados contienen solo texto/JSON propio.
