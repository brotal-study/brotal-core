// Capa de datos de estudio (arbol + evaluacion) conectada a FastAPI (/api/v1/*).
import { api } from './client'

export type Branch = 'theory' | 'practice'
export type CooldownMode = 'semester' | 'urgency'
export type ChallengeType =
  | 'concept'
  | 'trace'
  | 'debug'
  | 'implement'
  | 'fill_blank'
  | 'translate'
  | 'speaking_prompt'
export type CodeLanguage = 'java' | 'sql' | 'python' | 'c' | 'en' | 'text'
export type EngineType = 'concept_tree' | 'code_lab' | 'language_studio'
export type TtsLang = 'en' | 'es'
export type TtsAccent = 'us' | 'gb' | 'au'

export interface EvalPrompt {
  id: string
  question: string
  rubric_points: string[]
  challenge_type?: ChallengeType | null
  language?: CodeLanguage | null
  starter_code?: string | null
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
  engine_type?: EngineType | string
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

export interface CodeFixItem {
  broken_snippet: string
  fixed_snippet: string
  why: string
}

export type PromptReviewStatus = 'passed' | 'partial' | 'failed'

export interface PromptReviewItem {
  prompt_id: string
  status: PromptReviewStatus
  diagnosis: string
  code_fixes?: CodeFixItem[]
  corrected_solution?: string | null
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
  prompt_reviews?: PromptReviewItem[]
  routing_suggestion?: string | null
}

export interface RegenerateStoryResponse {
  course_id: string
  node_id: string
  story_script: string
  provider: string
}

export interface RegenerateQuestionsResponse {
  course_id: string
  node_id: string
  eval_prompts: EvalPrompt[]
  provider: string
}

export interface SuggestedNode {
  id: string
  title: string
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
  suggested_nodes?: SuggestedNode[]
}

export interface ExamRouteRequest {
  exam_date: string
  hours_per_day: number
  goal?: string
  exam_topics?: string
}

export interface ExamRouteStep {
  node_id: string | null
  node_title: string
  branch: string
  action: 'study_and_eval' | 'spaced_review' | 'practice_exam' | 'custom' | string
  target_mastery: number
  estimated_minutes: number
  reason: string
}

export interface ExamRouteDay {
  day_label: string
  date: string
  focus: string
  steps: ExamRouteStep[]
}

export interface ExamRouteResponse {
  course_id: string
  course_title: string
  exam_date: string
  days_left: number
  hours_per_day: number
  goal: string
  exam_topics: string
  strategy_summary: string
  recommended_cooldown_mode: CooldownMode
  days: ExamRouteDay[]
  uncovered_topics: string[]
  provider: string
  updated_at: string
}

export type StoryboardVariant =
  | 'execution_trace'
  | 'oop_dispatch'
  | 'error_contrast'
  | 'data_structure'
  | 'sql_pipeline'

export interface StoryboardSubgoal {
  id: string
  label: string
}

export interface StoryboardCheckpoint {
  enabled: boolean
  question: string
  options: string[]
  correct_index: number
  explanation: string
}

export interface StoryboardStep {
  index: number
  subgoal_id: string
  active_lines: number[]
  caption: string
  sentence_index?: number | null
  checkpoint?: StoryboardCheckpoint | null
  state: Record<string, unknown>
}

export interface NodeStoryboardResponse {
  course_id: string
  node_id: string
  variant: StoryboardVariant
  language: string
  title: string
  source_code: string
  fixed_code?: string | null
  subgoals: StoryboardSubgoal[]
  steps: StoryboardStep[]
  provider: string
  updated_at: string
}

export interface StoryboardStreamProgress {
  stage: 'analyzing' | 'generating' | 'validating' | 'done' | 'error'
  pct: number
  label: string
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

/** POST /api/v1/study/{course_id}/{node_id}/regenerate-questions */
export async function regenerateQuestions(
  courseId: string,
  nodeId: string,
): Promise<RegenerateQuestionsResponse> {
  return api<RegenerateQuestionsResponse>(
    `/api/v1/study/${encodeURIComponent(courseId)}/${encodeURIComponent(nodeId)}/regenerate-questions`,
    { method: 'POST' },
  )
}

export interface TtsSentenceTiming {
  text: string
  start: number
  end: number
}

export interface TtsWordTiming {
  text: string
  start: number
  end: number
}

export interface TtsTimingsResponse {
  course_id: string
  node_id: string
  sentences?: TtsSentenceTiming[]
  words?: TtsWordTiming[]
  timings?: TtsSentenceTiming[]
}

export interface TtsTimingsData {
  sentences: TtsSentenceTiming[]
  words: TtsWordTiming[]
}

/** POST /api/v1/study/{course_id}/{node_id}/tts -> Blob MP3 */
export async function fetchNodeTtsBlob(
  courseId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const res = await fetch(
    `/api/v1/study/${encodeURIComponent(courseId)}/${encodeURIComponent(nodeId)}/tts`,
    { method: 'POST', signal },
  )
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.blob()
}

/** POST /api/v1/study/{course_id}/tts-phrase -> Blob MP3 */
export async function fetchPhraseTtsBlob(
  courseId: string,
  text: string,
  lang: TtsLang = 'en',
  accent: TtsAccent = 'us',
  signal?: AbortSignal,
): Promise<Blob> {
  const res = await fetch(
    `/api/v1/study/${encodeURIComponent(courseId)}/tts-phrase`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, lang, accent }),
      signal,
    },
  )
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.blob()
}

/** GET /api/v1/study/{course_id}/{node_id}/tts-timings */
export async function fetchNodeTtsTimingsData(
  courseId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<TtsTimingsData> {
  try {
    const res = await api<TtsTimingsResponse>(
      `/api/v1/study/${encodeURIComponent(courseId)}/${encodeURIComponent(nodeId)}/tts-timings`,
      { signal },
    )
    const sentences = Array.isArray(res.sentences)
      ? res.sentences
      : Array.isArray(res.timings)
        ? res.timings
        : []
    const words = Array.isArray(res.words) ? res.words : []
    return { sentences, words }
  } catch (err) {
    if (signal?.aborted) throw err
    return { sentences: [], words: [] }
  }
}

/** GET /api/v1/courses/{course_id}/exam-route -> ruta guardada o null si no existe. */
export async function getExamRoute(courseId: string): Promise<ExamRouteResponse | null> {
  const res = await fetch(`/api/v1/courses/${encodeURIComponent(courseId)}/exam-route`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return (await res.json()) as ExamRouteResponse
}

/** POST /api/v1/courses/{course_id}/exam-route -> genera y guarda ruta de examen IA. */
export async function generateExamRoute(
  courseId: string,
  req: ExamRouteRequest,
): Promise<ExamRouteResponse> {
  return api<ExamRouteResponse>(`/api/v1/courses/${encodeURIComponent(courseId)}/exam-route`, {
    method: 'POST',
    body: JSON.stringify(req),
  })
}

export async function fetchNodeTtsTimings(
  courseId: string,
  nodeId: string,
): Promise<TtsSentenceTiming[]> {
  const data = await fetchNodeTtsTimingsData(courseId, nodeId)
  return data.sentences
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

/** GET /api/v1/study/{course_id}/{node_id}/storyboard -> storyboard guardado o null si 404. */
export async function getNodeStoryboard(
  courseId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<NodeStoryboardResponse | null> {
  const res = await fetch(
    `/api/v1/study/${encodeURIComponent(courseId)}/${encodeURIComponent(nodeId)}/storyboard`,
    { signal },
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return (await res.json()) as NodeStoryboardResponse
}

/** POST /api/v1/study/{course_id}/{node_id}/storyboard?force=... */
export async function generateNodeStoryboard(
  courseId: string,
  nodeId: string,
  force = false,
  signal?: AbortSignal,
): Promise<NodeStoryboardResponse> {
  return api<NodeStoryboardResponse>(
    `/api/v1/study/${encodeURIComponent(courseId)}/${encodeURIComponent(nodeId)}/storyboard?force=${force ? 'true' : 'false'}`,
    { method: 'POST', signal },
  )
}

function isAbortError(err: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true
  return err instanceof DOMException && err.name === 'AbortError'
}

/** GET /api/v1/study/{course_id}/{node_id}/storyboard/stream?force=... (SSE con fallback POST). */
export async function streamNodeStoryboard(
  courseId: string,
  nodeId: string,
  opts?: {
    force?: boolean
    onProgress?: (p: StoryboardStreamProgress) => void
    signal?: AbortSignal
  },
): Promise<NodeStoryboardResponse> {
  const force = Boolean(opts?.force)
  const onProgress = opts?.onProgress
  const signal = opts?.signal

  const parseSseDataLine = (rawLine: string): NodeStoryboardResponse | null => {
    const trimmed = rawLine.trim()
    if (!trimmed.startsWith('data:')) return null
    const jsonStr = trimmed.slice(5).trim()
    if (!jsonStr) return null
    const payload = JSON.parse(jsonStr) as {
      stage?: StoryboardStreamProgress['stage']
      pct?: number
      label?: string
      detail?: string
      storyboard?: NodeStoryboardResponse
    }
    if (payload.stage && typeof payload.pct === 'number') {
      onProgress?.({
        stage: payload.stage,
        pct: payload.pct,
        label: payload.label ?? '',
      })
    }
    if (payload.stage === 'error') {
      throw new Error(payload.label || payload.detail || 'Error en stream de storyboard')
    }
    if (payload.stage === 'done' && payload.storyboard) {
      return payload.storyboard
    }
    return null
  }

  try {
    const res = await fetch(
      `/api/v1/study/${encodeURIComponent(courseId)}/${encodeURIComponent(nodeId)}/storyboard/stream?force=${force ? 'true' : 'false'}`,
      {
        headers: { Accept: 'text/event-stream' },
        signal,
      },
    )
    if (!res.ok || !res.body) {
      throw new Error(`${res.status} ${res.statusText}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        const result = parseSseDataLine(line)
        if (result) return result
      }
    }

    buffer += decoder.decode()
    if (buffer.trim()) {
      for (const line of buffer.split('\n')) {
        const result = parseSseDataLine(line)
        if (result) return result
      }
    }

    throw new Error('Stream finalizado sin storyboard')
  } catch (err) {
    if (isAbortError(err, signal)) {
      throw err
    }
    onProgress?.({
      stage: 'generating',
      pct: 52,
      label: 'Construyendo pasos y estado en memoria...',
    })
    const storyboard = await generateNodeStoryboard(courseId, nodeId, force, signal)
    onProgress?.({
      stage: 'done',
      pct: 100,
      label: 'Animación lista',
    })
    return storyboard
  }
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
