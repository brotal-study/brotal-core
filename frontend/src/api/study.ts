// Capa de datos de estudio (arbol + evaluacion).
// HOY: mock local sobre fixtures/demo_pack.json con progreso persistido en localStorage.
// CUANDO el backend (#4) este listo, reemplazar el cuerpo de getTree/evaluate por `api(...)`.
// La UI solo depende de las firmas y tipos de este archivo.
import packFixture from '@fixtures/demo_pack.json'

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
  /**
   * Solo mock v0.1: puntos de rubrica marcados como cubiertos (`${prompt_id}::${indice}`).
   * En v1.0 el backend calcula la nota con el tutor IA y este campo desaparece.
   */
  covered_points: string[]
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
}

export const PASS_SCORE = 7.0
export const MAX_MASTERY = 3
/** Semestre: separa validaciones ~1 semana. Urgencia: 30 s para poder probar 0/3 -> 1/3 -> 2/3 en vivo. */
export const COOLDOWN_MS: Record<CooldownMode, number> = {
  semester: 7 * 24 * 60 * 60 * 1000,
  urgency: 30 * 1000,
}

const pack = packFixture as unknown as {
  id: string
  course_code: string
  title: string
  metadata: { world_metaphor?: string }
  nodes: PackNode[]
}

const STORAGE_KEY = 'brotal_study_progress'
type Stored = Record<string, Record<string, NodeProgress>>

const tick = () => new Promise<void>((r) => setTimeout(r, 0))
const read = (): Stored => {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') as Stored
  } catch {
    return {}
  }
}
const write = (s: Stored) => localStorage.setItem(STORAGE_KEY, JSON.stringify(s))

const emptyProgress = (node_id: string): NodeProgress => ({
  node_id,
  mastery_level: 0,
  next_review_at: null,
  training_reps: 0,
  best_score: 0,
  last_score: null,
  last_practiced_at: null,
})

export const inCooldown = (p: NodeProgress, now = Date.now()): boolean =>
  p.next_review_at !== null && new Date(p.next_review_at).getTime() > now

/** Acepta el id del pack o el codigo del ramo (INF2324). */
const matches = (courseId: string) => courseId === pack.id || courseId === pack.course_code

/** GET /api/v1/courses/{course_id}/tree  -> nodos + node_progress. null si el ramo no tiene Pack. */
export async function getTree(courseId: string): Promise<CourseTree | null> {
  await tick()
  if (!matches(courseId)) return null
  const stored = read()[pack.id] ?? {}
  const progress: Record<string, NodeProgress> = {}
  for (const n of pack.nodes) progress[n.id] = stored[n.id] ?? emptyProgress(n.id)
  return {
    course_id: pack.id,
    course_code: pack.course_code,
    title: pack.title,
    world_metaphor: pack.metadata.world_metaphor ?? null,
    nodes: pack.nodes,
    progress,
  }
}

/** Solo mock: borra el progreso local del ramo (no existe en el contrato real). */
export async function resetProgress(courseId: string): Promise<void> {
  if (!matches(courseId)) return
  const s = read()
  delete s[pack.id]
  write(s)
}

/** POST /api/v1/study/{course_id}/{node_id}/evaluate */
export async function evaluate(
  courseId: string,
  nodeId: string,
  req: EvaluateRequest,
  now = Date.now(),
): Promise<EvaluateResponse> {
  await tick()
  const node = pack.nodes.find((n) => n.id === nodeId)
  if (!matches(courseId) || !node) throw new Error('Nodo no encontrado')

  const covered = new Set(req.covered_points)
  const feedback: PointFeedback[] = node.eval_prompts.flatMap((q) =>
    q.rubric_points.map((point, point_index) => ({
      prompt_id: q.id,
      point_index,
      point,
      covered: covered.has(`${q.id}::${point_index}`),
    })),
  )
  const score = scoreFromFeedback(feedback)
  const passed = score >= PASS_SCORE

  const all = read()
  const course = (all[pack.id] ??= {})
  const prev = course[nodeId] ?? emptyProgress(nodeId)
  const next: NodeProgress = {
    ...prev,
    best_score: Math.max(prev.best_score, score),
    last_score: score,
    last_practiced_at: new Date(now).toISOString(),
  }

  // Regla del contrato: solo la validacion fuera de cooldown sube mastery; en cooldown suma Reps.
  let counted = false
  if (passed) {
    if (!inCooldown(prev, now) && prev.mastery_level < MAX_MASTERY) {
      next.mastery_level = prev.mastery_level + 1
      next.next_review_at = new Date(now + COOLDOWN_MS[req.cooldown_mode]).toISOString()
      counted = true
    } else {
      next.training_reps = prev.training_reps + 1
    }
  }
  course[nodeId] = next
  write(all)
  return { score, passed, counted_mastery: counted, feedback, progress: next }
}

/** Nota 1.0..10.0 proporcional a puntos cubiertos (promedio simple sobre todos los puntos). */
export function scoreFromFeedback(feedback: { covered: boolean }[]): number {
  if (feedback.length === 0) return 1
  const ratio = feedback.filter((f) => f.covered).length / feedback.length
  return Math.round((1 + 9 * ratio) * 10) / 10
}

// ---------------- Evaluador demo local (solo v0.1) ----------------

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

/**
 * Evaluador por palabras clave: un punto se marca cubierto si la respuesta contiene todas sus siglas
 * y al menos la mitad de sus raices. Es impreciso a proposito; el usuario puede corregirlo.
 * Evaluador demo local — en v1.0 evalua el tutor IA.
 */
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
