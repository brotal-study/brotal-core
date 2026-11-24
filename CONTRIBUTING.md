# Contribuir a Brotal

Gracias por sumarte. Flujo único: **Issues → Branch → PR → Review**.

## 1. Issue primero
Toda tarea parte de un Issue con descripción, archivos a tocar y criterios de aceptación. Comenta en el Issue que lo tomas para no duplicar trabajo.

## 2. Branch
Desde `main` actualizado:

```bash
git switch main && git pull
git switch -c <tipo>/<issue>-<descripcion-corta>   # ej. feat/2-backend-base
```

Tipos: `feat`, `fix`, `docs`, `test`, `chore`. Nunca se hace push directo a `main`.

## 3. Commits
Mensajes en imperativo, pequeños y con referencia: `feat(backend): agrega GET /api/v1/profile (#2)`.

## 4. Pull Request
- Un PR por Issue, con `Closes #N` en la descripción.
- Backend: `pytest` verde. Frontend: `npm run build` sin errores.
- `python3 scripts/validate_fixtures.py` verde si tocas contratos o fixtures.
- Si cambias un contrato (JSON, SQL o API), actualiza `schema.sql` y/o los modelos Pydantic en el mismo PR y avísalo en la descripción.

## 5. Review
Al menos 1 aprobación de un mantenedor antes de hacer merge. Preferimos *squash and merge*.

## Reparto inicial
- **Backend** (Python/FastAPI/SQLite): `backend/`, Issues `#2`, `#3`, `#4`.
- **Frontend** (React/TS): `frontend/`, Issues `#5`, `#6`, `#7`.
- El contrato entre ambos es `/openapi.json`; el frontend genera tipos con `npm run gen:api`.

## Reglas no negociables
- Cero emojis en el frontend (solo `lucide-react`), tema claro/oscuro, sin login.
- Cero claves reales (solo `.env.example`) y cero notas personales.
- Cero PDFs/PPTX/DOCX con copyright en el repo ni en los fixtures.
- Los aportes se publican bajo [AGPLv3](LICENSE).
