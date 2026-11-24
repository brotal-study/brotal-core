#!/usr/bin/env python3
"""Valida fixtures/demo_career.json y demo_pack.json contra el contrato v0.1."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "fixtures"
errors: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)


career = json.loads((ROOT / "demo_career.json").read_text(encoding="utf-8"))
pack = json.loads((ROOT / "demo_pack.json").read_text(encoding="utf-8"))

check(career.get("schema_version") == "1.0", "career: schema_version != 1.0")
cats = {c["id"] for c in career["categories"]}
codes: list[str] = []
for sem in career["semesters"]:
    for c in sem["courses"]:
        codes.append(c["code"])
        check(c["category"] in cats, f"career: categoría inválida en {c['code']}")
        check(isinstance(c["credits"], int) and c["credits"] > 0, f"career: créditos {c['code']}")
check(len(codes) == len(set(codes)), "career: códigos duplicados")
for sem in career["semesters"]:
    for c in sem["courses"]:
        for p in c["prerequisites"]:
            check(p in codes, f"career: prerrequisito inexistente {p} en {c['code']}")

check(pack.get("schema_version") == "1.0", "pack: schema_version != 1.0")
check(pack["engine_type"] in {"concept_tree", "code_lab", "language_studio"}, "pack: engine_type")
check(pack["course_code"] in codes, "pack: course_code no está en la malla")
for cid in pack["metadata"]["career_ids"]:
    check(cid == career["id"], f"pack: career_id desconocido {cid}")
ids = [n["id"] for n in pack["nodes"]]
check(len(ids) == len(set(ids)), "pack: ids de nodo duplicados")
for n in pack["nodes"]:
    check(n["branch"] in {"theory", "practice"}, f"pack: branch {n['id']}")
    for p in n["parent_ids"]:
        check(p in ids, f"pack: parent inexistente {p} en {n['id']}")
    check(bool(n["eval_prompts"]), f"pack: sin eval_prompts en {n['id']}")

if errors:
    print("\n".join(errors))
    sys.exit(1)
print(f"OK: {len(codes)} ramos, {len(ids)} nodos")
