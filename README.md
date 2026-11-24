# Brotal

Motor open-source y local-first de estudio activo: convierte apuntes en árboles de habilidades (`0/3 → 3/3`) con evaluación a ciegas (aprobación `>= 7/10`), tutor socrático y paquetes comunitarios de ramos (*Course Packs*).

- **Local-first y sin login:** perfil local en SQLite (`~/.brotal/brotal.db`).
- **BYOK, costo `$0`:** usa tus propias claves gratuitas (Groq, Gemini Free) u Ollama local. Ver `.env.example`.
- **Cero contenido de ramos en el motor:** solo `fixtures/` con datos de prueba. Los Course Packs viven en repos aparte.
- **Licencia:** [AGPLv3](LICENSE).

> Estado: `v0.1` (cimientos). Backend con stubs; ver issues abiertos.

## Estructura

```text
backend/    Python 3.11+ · FastAPI · SQLite · Pydantic v2
frontend/   Vite · React · TypeScript · Tailwind · lucide-react · zustand
plugins/    Módulos opcionales (p. ej. pronounce-ipa, v1.2)
fixtures/   demo_career.json (CareerManifest) y demo_pack.json (CoursePack)
scripts/    validate_fixtures.py
docs/       Textos de issues y notas
```

## Inicio rápido

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
```

Validar fixtures: `python3 scripts/validate_fixtures.py`

## Reglas de UI (permanentes)

- Cero emojis en la interfaz: solo íconos SVG de `lucide-react`.
- Tema Claro/Oscuro (`localStorage.brotal_theme`).
- Sin login ni cuentas: Perfil Local.

## Privacidad y copyright

No subas notas personales, claves reales, ni PDFs/PPTX/DOCX de terceros (profesores, editoriales). Los Course Packs contienen solo texto/JSON propio.
