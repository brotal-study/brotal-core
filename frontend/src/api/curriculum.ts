// Capa de datos de malla y packs.
// HOY: lee los fixtures locales. CUANDO el backend (#2, #3) este listo, reemplazar
// el cuerpo de cada funcion por su `api(...)` equivalente (indicado en cada una).
import careerFixture from '@fixtures/demo_career.json'
import packFixture from '@fixtures/demo_pack.json'
import type { CareerManifest, CareerSummary, PackSummary } from './types'

const career = careerFixture as unknown as CareerManifest
const pack = packFixture as unknown as {
  id: string
  course_code: string
  title: string
  metadata: PackSummary['metadata']
  nodes: unknown[]
}

const tick = () => new Promise<void>((r) => setTimeout(r, 0))

/** GET /api/v1/registry/careers */
export async function listCareers(): Promise<CareerSummary[]> {
  await tick()
  return [
    {
      id: career.id,
      country: career.country,
      university: career.university.name,
      university_short: career.university.short_name,
      name: career.career.name,
      plan_ref: career.career.plan_ref,
    },
  ]
}

/** GET /api/v1/registry/careers/{id} */
export async function getCareer(id: string): Promise<CareerManifest | null> {
  await tick()
  return id === career.id ? career : null
}

/** GET /api/v1/registry/packs?career_id=... (un resumen por pack disponible) */
export async function listPacks(careerId: string): Promise<PackSummary[]> {
  await tick()
  if (!pack.metadata.career_ids.includes(careerId)) return []
  return [
    {
      id: pack.id,
      course_code: pack.course_code,
      title: pack.title,
      metadata: pack.metadata,
      node_count: pack.nodes.length,
    },
  ]
}

/** POST /api/v1/packs/install  { pack_id } */
export async function installPack(packId: string): Promise<{ pack_id: string; version: string }> {
  await tick()
  if (packId !== pack.id) throw new Error('Pack no encontrado')
  return { pack_id: pack.id, version: pack.metadata.version }
}
