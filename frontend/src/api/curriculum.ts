// Capa de datos de perfil, malla, ramos y packs conectada a FastAPI (/api/v1/*).
import { api } from './client'
import type { CareerManifest, CareerSummary, CourseStatus, PackSummary } from './types'

export interface ApiProfile {
  id: number
  display_name: string
  career_id: string | null
  curriculum_mode: 'realistic' | 'free'
  cooldown_mode: 'semester' | 'urgency'
  theme: 'dark' | 'light'
  ai_provider: 'auto' | 'groq' | 'gemini' | 'ollama'
  created_at: string
  providers: { groq: boolean; gemini: boolean; ollama: boolean }
}

export interface ApiProfilePatch {
  display_name?: string
  career_id?: string | null
  curriculum_mode?: 'realistic' | 'free'
  cooldown_mode?: 'semester' | 'urgency'
  theme?: 'dark' | 'light'
  ai_provider?: 'auto' | 'groq' | 'gemini' | 'ollama'
}

export interface CareerDetail extends CareerManifest {
  statuses: Record<string, CourseStatus>
  installed_packs: Record<string, string>
  credits_total: number
  credits_passed: number
  courses_total: number
  courses_passed: number
}

export interface RegistryResponse {
  schema_version: string
  updated_at: string
  careers: CareerSummary[]
  packs: (PackSummary & { career_ids?: string[] })[]
}

export interface ApiCourse {
  id: string
  career_id: string | null
  course_code: string | null
  code: string
  title: string
  name: string
  credits: number
  category: string
  engine_type: string
  status: CourseStatus
  source_type: 'pack' | 'local'
  pack_version: string | null
  manual: boolean
  updated_at: string
}

/** GET /api/v1/profile */
export async function getProfile(): Promise<ApiProfile> {
  return api<ApiProfile>('/api/v1/profile')
}

/** PATCH /api/v1/profile */
export async function patchProfile(patch: ApiProfilePatch): Promise<ApiProfile> {
  return api<ApiProfile>('/api/v1/profile', {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

/** GET /api/v1/registry -> careers */
export async function listCareers(): Promise<CareerSummary[]> {
  const reg = await api<RegistryResponse>('/api/v1/registry')
  return reg.careers
}

/** GET /api/v1/careers/{id} */
export async function getCareer(id: string): Promise<CareerDetail | null> {
  const res = await fetch(`/api/v1/careers/${encodeURIComponent(id)}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return (await res.json()) as CareerDetail
}

/** GET /api/v1/registry -> packs filtrados por careerId */
export async function listPacks(careerId: string): Promise<PackSummary[]> {
  const reg = await api<RegistryResponse>('/api/v1/registry')
  return reg.packs.filter(
    (p) => (p.career_ids ?? p.metadata?.career_ids ?? []).includes(careerId),
  )
}

/** POST /api/v1/courses/install-pack */
export async function installPack(
  packId: string,
): Promise<{ pack_id: string; course_id: string; version: string }> {
  return api<{ pack_id: string; course_id: string; version: string }>(
    '/api/v1/courses/install-pack',
    {
      method: 'POST',
      body: JSON.stringify({ pack_id: packId }),
    },
  )
}

/** POST /api/v1/careers/{career_id}/bulk-status */
export async function bulkApproveCareer(
  careerId: string,
  upToSemester: number,
  status: CourseStatus = 'passed',
): Promise<{ updated_count: number }> {
  return api<{ updated_count: number }>(
    `/api/v1/careers/${encodeURIComponent(careerId)}/bulk-status`,
    {
      method: 'POST',
      body: JSON.stringify({ up_to_semester: upToSemester, status }),
    },
  )
}

/** GET /api/v1/courses */
export async function listUserCourses(status?: CourseStatus): Promise<ApiCourse[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return api<ApiCourse[]>(`/api/v1/courses${qs}`)
}

/** POST /api/v1/courses/manual */
export async function createManualCourse(course: {
  id?: string
  code: string
  name: string
  credits: number
  category: string
}): Promise<ApiCourse> {
  return api<ApiCourse>('/api/v1/courses/manual', {
    method: 'POST',
    body: JSON.stringify(course),
  })
}

/** PATCH /api/v1/courses/{course_id} */
export async function patchCourseStatus(
  courseId: string,
  status: CourseStatus,
): Promise<ApiCourse> {
  return api<ApiCourse>(`/api/v1/courses/${encodeURIComponent(courseId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  })
}

/** DELETE /api/v1/courses/{course_id} */
export async function deleteCourse(courseId: string): Promise<void> {
  await api<{ deleted: string }>(`/api/v1/courses/${encodeURIComponent(courseId)}`, {
    method: 'DELETE',
  })
}

export interface ProvidersSettings {
  ai_provider: 'auto' | 'groq' | 'gemini' | 'ollama'
  active_provider: string
  active_model: string
  providers: { groq: boolean; gemini: boolean; ollama: boolean }
  models: { groq: string; gemini: string; ollama: string; ollama_url: string }
}

export interface ProvidersSettingsUpdate {
  ai_provider?: 'auto' | 'groq' | 'gemini' | 'ollama'
  groq_api_key?: string
  gemini_api_key?: string
  ollama_url?: string
  groq_model?: string
  gemini_model?: string
  ollama_model?: string
}

/** GET /api/v1/settings/providers */
export async function getProvidersSettings(): Promise<ProvidersSettings> {
  return api<ProvidersSettings>('/api/v1/settings/providers')
}

/** PUT /api/v1/settings/providers */
export async function putProvidersSettings(
  update: ProvidersSettingsUpdate,
): Promise<ProvidersSettings> {
  return api<ProvidersSettings>('/api/v1/settings/providers', {
    method: 'PUT',
    body: JSON.stringify(update),
  })
}

export interface ProcessedFileSummary {
  filename: string
  sections: number
  chars: number
}

export interface IngestLocalResponse {
  course_id: string
  course_code: string
  title: string
  status: CourseStatus
  node_count: number
  chunks_indexed: number
  processed_files: ProcessedFileSummary[]
  provider: string
  world_metaphor: string
}

/** POST /api/v1/courses/ingest-local (multipart/form-data) */
export async function ingestLocalFiles(params: {
  course_code: string
  title: string
  career_id?: string | null
  world_metaphor?: string
  files: File[]
}): Promise<IngestLocalResponse> {
  const form = new FormData()
  form.append('course_code', params.course_code)
  form.append('title', params.title)
  if (params.career_id) form.append('career_id', params.career_id)
  if (params.world_metaphor) form.append('world_metaphor', params.world_metaphor)
  for (const file of params.files) {
    form.append('files', file)
  }
  const res = await fetch('/api/v1/courses/ingest-local', {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const errText = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status} ${errText}`)
  }
  return (await res.json()) as IngestLocalResponse
}
