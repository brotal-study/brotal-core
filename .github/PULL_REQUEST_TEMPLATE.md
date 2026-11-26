## Issue vinculado

Closes #

## Resumen de cambios

- 

## Uso de asistente IA (opcional)

- [ ] No usé asistente IA / Usé asistente IA (Claude Code, Cursor, Antigravity, etc.) habiendo cargado y respetado `CLAUDE.md` y revisado manualmente cada línea.

## Checklist obligatorio antes de pedir revisión

- [ ] `cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app tests` pasa sin errores.
- [ ] `python3 scripts/validate_fixtures.py` valida correctamente `demo_career.json` y `demo_pack.json`.
- [ ] `cd frontend && npm run build` compila sin errores de TypeScript ni Vite.
- [ ] Cero emojis Unicode en `frontend/src` (solo íconos SVG de `lucide-react`) y soporte verificado en Tema Claro y Oscuro.
- [ ] Sin datos personales, sin claves reales y sin archivos con copyright (`.pdf`, `.pptx`, `.docx`).
- [ ] Si toqué SQLite o schemas Pydantic, los cambios son idempotentes y retrocompatibles.
