# AGENTS.md — Instrucciones para Agentes de IA

Cualquier agente de inteligencia artificial que opere en este repositorio (**Antigravity**, **Claude Code**, **Cursor**, **Codex**, **Copilot**, **Windsurf** u otros) **DEBE leer y cumplir estrictamente [`CLAUDE.md`](./CLAUDE.md)** antes de analizar, planificar o modificar cualquier archivo.

## Fuente Única de Verdad

Para evitar duplicación o desincronización de reglas, toda la especificación técnica vive en [`CLAUDE.md`](./CLAUDE.md):

1. **Identidad y límites del producto:** motor open-source ([AGPLv3](LICENSE)), local-first, sin login y costo `$0` (BYOK) para estudio activo a ciegas (`>= 7/10` + `0/3 -> 3/3`).
2. **Arquitectura vigente (`v1.1.2`):** mapa exacto de `backend/`, `frontend/`, `fixtures/`, `scripts/` y `./brotal`.
3. **Reglas innegociables:** cero emojis en `frontend/src` (solo `lucide-react`), soporte Claro/Oscuro, nodos rectangulares y copa en columnas paralelas, SQLite idempotente, schemas Pydantic retrocompatibles y cero dependencias pesadas (sin PyTorch/Docker).
4. **Verificación obligatoria antes de entregar cambios:** `pytest`, `ruff`, `validate_fixtures.py`, `npm run build`, chequeo de 0 emojis y `./brotal --check`.
