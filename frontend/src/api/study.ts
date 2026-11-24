// Capa de datos de estudio (arbol + evaluacion) conectada a FastAPI (/api/v1/*).
import { api } from './client'

export type Branch = 'theory' | 'practice'
export type CooldownMode = 'semester' | 'urgency'

export interface EvalPrompt {
  id: string
  question: string
  rubric_points: string[]
}

export interface PackNode {
  id: string
  parent_ids: string[]
  branch: Branch
  block: string
  title: string
  summary: string
  story_script: string
  eval_prompts: EvalPrompt[]
  storyboard_ref: string | null
}

/** Espeja la tabla node_progress (docs/CONTRATO-V0.1.md, seccion 4). */
export interface NodeProgress {
  node_id: string
  mastery_level: number // 0..3 (retencion honesta)
  next_review_at: string | null // ISO; si es futuro => cooldown activo
  training_reps: number // practica (no sube mastery)
  best_score: number
  last_score: number | null
  last_practiced_at: string | null
}

export interface CourseTree {
  course_id: string
  course_code: string
  title: string
  world_metaphor: string | null
  nodes: PackNode[]
  progress: Record<string, NodeProgress>
}

export interface EvaluateRequest {
  /** Respuestas por id de pregunta, en el orden mezclado en que se respondieron. */
  answers: { prompt_id: string; text: string }[]
  cooldown_mode: CooldownMode
  /** Puntos de rubrica marcados como cubiertos (`${prompt_id}::${indice}`). Si se omite, evalua con IA en backend. */
  covered_points?: string[]
}

export interface PointFeedback {
  prompt_id: string
  point_index: number
  point: string
  covered: boolean
}

export interface EvaluateResponse {
  score: number // 1.0 .. 10.0
  passed: boolean // score >= 7.0
  counted_mastery: boolean // true si subio 0/3 -> 3/3
  feedback: PointFeedback[]
  progress: NodeProgress
  imprecisions?: string[]
  re_explanation?: string | null
  evaluated_by?: string
}

export interface RegenerateStoryResponse {
  course_id: string
  node_id: string
  story_script: string
  provider: string
}

export interface ChatMessage {
  id: number
  course_id: string
  node_id: string | null
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface ChatResponse {
  user_message: ChatMessage
  assistant_message: ChatMessage
  provider: string
}

export const PASS_SCORE = 7.0
export const MAX_MASTERY = 3
export const COOLDOWN_MS: Record<CooldownMode, number> = {
  semester: 7 * 24 * 60 * 60 * 1000,
  urgency: 30 * 1000,
}

export const inCooldown = (p: NodeProgress, now = Date.now()): boolean =>
  p.next_review_at !== null && new Date(p.next_review_at).getTime() > now

/** GET /api/v1/courses/{course_id}/tree -> nodos + node_progress. null si el ramo no tiene Pack. */
export async function getTree(courseId: string): Promise<CourseTree | null> {
  const res = await fetch(`/api/v1/courses/${encodeURIComponent(courseId)}/tree`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return (await res.json()) as CourseTree
}

/** POST /api/v1/courses/{course_id}/reset-progress */
export async function resetProgress(courseId: string): Promise<void> {
  await api<{ course_id: string; reset: boolean }>(
    `/api/v1/courses/${encodeURIComponent(courseId)}/reset-progress`,
    { method: 'POST' },
  )
}

/** POST /api/v1/study/{course_id}/{node_id}/evaluate */
export async function evaluate(
  courseId: string,
  nodeId: string,
  req: EvaluateRequest,
): Promise<EvaluateResponse> {
  return api<EvaluateResponse>(
    `/api/v1/study/${encodeURIComponent(courseId)}/${encodeURIComponent(nodeId)}/evaluate`,
    {
      method: 'POST',
      body: JSON.stringify(req),
    },
  )
}

/** POST /api/v1/study/{course_id}/{node_id}/regenerate-story */
export async function regenerateStory(
  courseId: string,
  nodeId: string,
): Promise<RegenerateStoryResponse> {
  return api<RegenerateStoryResponse>(
    `/api/v1/study/${encodeURIComponent(courseId)}/${encodeURIComponent(nodeId)}/regenerate-story`,
    { method: 'POST' },
  )
}

/** POST /api/v1/study/{course_id}/{node_id}/tts -> Blob MP3 */
export async function fetchNodeTtsBlob(courseId: string, nodeId: string): Promise<Blob> {
  const res = await fetch(
    `/api/v1/study/${encodeURIComponent(courseId)}/${encodeURIComponent(nodeId)}/tts`,
    { method: 'POST' },
  )
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.blob()
}

/** GET /api/v1/chat/{course_id} */
export async function getChatHistory(courseId: string): Promise<ChatMessage[]> {
  return api<ChatMessage[]>(`/api/v1/chat/${encodeURIComponent(courseId)}`)
}

/** POST /api/v1/chat/{course_id} */
export async function sendChatMessage(
  courseId: string,
  message: string,
  nodeId?: string | null,
): Promise<ChatResponse> {
  return api<ChatResponse>(`/api/v1/chat/${encodeURIComponent(courseId)}`, {
    method: 'POST',
    body: JSON.stringify({ message, node_id: nodeId ?? null }),
  })
}

/** DELETE /api/v1/chat/{course_id} */
export async function clearChatHistory(courseId: string): Promise<void> {
  await api<{ course_id: string; deleted: number }>(
    `/api/v1/chat/${encodeURIComponent(courseId)}`,
    { method: 'DELETE' },
  )
}

/** Nota 1.0..10.0 proporcional a puntos cubiertos (promedio simple sobre todos los puntos). */
export function scoreFromFeedback(feedback: { covered: boolean }[]): number {
  if (feedback.length === 0) return 1
  const ratio = feedback.filter((f) => f.covered).length / feedback.length
  return Math.round((1 + 9 * ratio) * 10) / 10
}

// ---------------- Pre-evaluador local de apoyo en UI (v0.1) ----------------

const norm = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')

const STOP = new Set(
  (
    'identifica explica menciona distingue relaciona justifica define describe ejemplo valido ' +
    'para como este esta esto sobre entre desde cada tiene tambien porque cual cuales ' +
    'que los las una uno unos unas del con por sus ser son sin mas muy'
  ).split(' '),
)

function keywords(point: string): { stems: string[]; acronyms: string[] } {
  const acronyms = (point.match(/\b[A-Z][A-Z0-9-]{1,}\b/g) ?? []).map(norm)
  const stems = norm(point)
    .split(/[^a-z0-9]+/)
    .filter((w) => w.length >= 4 && !STOP.has(w))
    .map((w) => w.slice(0, 5))
  return { stems: [...new Set(stems)], acronyms }
}

export function previewGrade(node: PackNode, answers: Record<string, string>): PointFeedback[] {
  return node.eval_prompts.flatMap((q) => {
    const text = norm(answers[q.id] ?? '')
    const words = text.split(/[^a-z0-9]+/)
    return q.rubric_points.map((point, point_index) => {
      const { stems, acronyms } = keywords(point)
      const hasAcr = acronyms.every((a) => words.includes(a))
      const hit = stems.filter((s) => words.some((w) => w.startsWith(s))).length
      const ok = text.length > 0 && hasAcr && (stems.length === 0 || hit / stems.length >= 0.5)
      return { prompt_id: q.id, point_index, point, covered: ok }
    })
  })
}
