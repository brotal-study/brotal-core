import { useEffect, useRef, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { oneDark } from '@codemirror/theme-one-dark'
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Bug,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleX,
  Code2,
  Compass,
  Cpu,
  EyeOff,
  GraduationCap,
  Info,
  Languages,
  Layers,
  Loader2,
  MessageCircle,
  MessageSquare,
  Mic,
  PenLine,
  RefreshCw,
  RotateCcw,
  Send,
  Shuffle,
  Terminal,
  Wrench,
} from 'lucide-react'
import {
  inCooldown,
  MAX_MASTERY,
  PASS_SCORE,
  previewGrade,
  scoreFromFeedback,
  type EvalPrompt,
  type EvaluateResponse,
  type NodeProgress,
  type PackNode,
  type PromptReviewItem,
  type PromptReviewStatus,
  type TtsAccent,
} from '../../api/study'
import type { QuestionStyle } from '../../api/curriculum'
import { useAppStore } from '../../store/useAppStore'
import { useStudyStore } from '../../store/useStudyStore'
import MarkdownView from '../common/MarkdownView'
import CodeChallengeInput, {
  getLanguageExtension,
  sanitizeCodePrompt,
  type SupportLevel,
} from './CodeChallengeInput'
import { formatRemaining, useNow } from './studyUtils'

interface Props {
  courseId?: string
  engineType?: string
  node: PackNode
  progress: NodeProgress
  nextNode?: PackNode | null
  onSelectNextNode?: (nodeId: string) => void
  onSubmit: (req: {
    answers: { prompt_id: string; text: string }[]
    covered_points?: string[]
  }) => Promise<EvaluateResponse>
  onRegenerateQuestions: () => Promise<void>
  onBackToStory: () => void
  onAskTutor: (ctx: { prompt: string; banner: string; autoSend?: boolean }) => void
  /** true mientras hay respuestas/revision sin cerrar (para pedir confirmacion al salir). */
  onInProgressChange: (v: boolean) => void
}

const SUPPORT_LEVELS: { id: SupportLevel; label: string; detail: string }[] = [
  { id: 'guided', label: 'Guiado', detail: 'Audio 0.8x + guía de estructura' },
  { id: 'transition', label: 'Transición', detail: 'Texto en inglés + audio 0.95x' },
  { id: 'exam', label: 'Examen Real', detail: 'Audio 1.0x y oído primero en Speaking' },
]

type Phase = 'answering' | 'self_review' | 'result'

// Ultimo orden mostrado por nodo: el siguiente intento nunca repite la misma secuencia.
const lastOrder = new Map<string, string>()

function shuffled(nodeId: string, prompts: EvalPrompt[]): EvalPrompt[] {
  const key = (l: EvalPrompt[]) => l.map((p) => p.id).join(',')
  let out = prompts
  for (let tries = 0; tries < 20; tries++) {
    out = [...prompts]
    for (let i = out.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      ;[out[i], out[j]] = [out[j], out[i]]
    }
    if (prompts.length < 2 || key(out) !== lastOrder.get(nodeId)) break
  }
  lastOrder.set(nodeId, key(out))
  return out
}

function buildInitialAnswers(prompts: EvalPrompt[]): Record<string, string> {
  const init: Record<string, string> = {}
  for (const p of prompts) {
    if ((p.challenge_type === 'debug' || p.challenge_type === 'implement') && p.starter_code) {
      const { starterCode } = sanitizeCodePrompt(p.question, p.starter_code, p.language)
      init[p.id] = starterCode
    }
  }
  return init
}

function isPromptEditedOrAnswered(q: EvalPrompt, answers: Record<string, string>): boolean {
  const val = (answers[q.id] ?? '').trim()
  if (val.length === 0) return false
  if ((q.challenge_type === 'debug' || q.challenge_type === 'implement') && q.starter_code) {
    const { starterCode } = sanitizeCodePrompt(q.question, q.starter_code, q.language)
    return val !== starterCode.trim()
  }
  return true
}

export default function EvalTab({
  courseId,
  engineType,
  node,
  progress,
  nextNode = null,
  onSelectNextNode,
  onSubmit,
  onRegenerateQuestions,
  onBackToStory,
  onAskTutor,
  onInProgressChange,
}: Props) {
  const storeCourseId = useStudyStore((s) => s.tree?.course_id)
  const storeEngineType = useStudyStore((s) => s.tree?.engine_type)
  const effectiveCourseId = courseId ?? storeCourseId ?? 'default'
  const effectiveEngineType = engineType ?? storeEngineType ?? 'concept_tree'
  const isLanguageStudio = effectiveEngineType === 'language_studio'

  const questionStyle = useStudyStore((s) => s.questionStyle)
  const setQuestionStyle = useStudyStore((s) => s.setQuestionStyle)
  const [order, setOrder] = useState(() => shuffled(node.id, node.eval_prompts))
  const [answers, setAnswers] = useState<Record<string, string>>(() =>
    buildInitialAnswers(node.eval_prompts),
  )
  const [phase, setPhase] = useState<Phase>('answering')
  const [covered, setCovered] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<EvaluateResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [regeneratingQuestions, setRegeneratingQuestions] = useState(false)
  const [supportLevel, setSupportLevel] = useState<SupportLevel>(() =>
    progress.mastery_level === 0 ? 'guided' : progress.mastery_level === 1 ? 'transition' : 'exam',
  )
  const [accent, setAccent] = useState<TtsAccent>('us')

  useEffect(() => {
    setOrder(shuffled(node.id, node.eval_prompts))
    setAnswers(buildInitialAnswers(node.eval_prompts))
  }, [node.id, node.eval_prompts])

  const cooling = inCooldown(progress)
  const now = useNow(phase === 'result' && cooling)
  const prevInProgress = useRef(false)
  useEffect(() => {
    const v = phase !== 'result'
    if (v !== prevInProgress.current) {
      prevInProgress.current = v
      onInProgressChange(v)
    }
  }, [phase, onInProgressChange])
  useEffect(() => () => onInProgressChange(false), [onInProgressChange])

  const hasAnswer = order.some((q) => isPromptEditedOrAnswered(q, answers))

  const evaluateWithAi = async () => {
    setBusy(true)
    try {
      const res = await onSubmit({
        answers: order.map((q) => ({ prompt_id: q.id, text: answers[q.id] ?? '' })),
      })
      setResult(res)
      setPhase('result')
    } finally {
      setBusy(false)
    }
  }

  const handleRegenerateQuestions = async () => {
    setRegeneratingQuestions(true)
    try {
      await onRegenerateQuestions()
      setCovered(new Set())
      setResult(null)
      setPhase('answering')
    } finally {
      setRegeneratingQuestions(false)
    }
  }

  const startSelfReview = () => {
    const auto = previewGrade(node, answers)
    setCovered(new Set(auto.filter((f) => f.covered).map((f) => `${f.prompt_id}::${f.point_index}`)))
    setPhase('self_review')
  }

  const confirmSelfReview = async () => {
    setBusy(true)
    try {
      const res = await onSubmit({
        answers: order.map((q) => ({ prompt_id: q.id, text: answers[q.id] ?? '' })),
        covered_points: [...covered],
      })
      setResult(res)
      setPhase('result')
    } finally {
      setBusy(false)
    }
  }

  const retry = () => {
    setOrder(shuffled(node.id, node.eval_prompts))
    setAnswers(buildInitialAnswers(node.eval_prompts))
    setCovered(new Set())
    setResult(null)
    setPhase('answering')
  }

  const toggle = (k: string) =>
    setCovered((s) => {
      const n = new Set(s)
      if (n.has(k)) n.delete(k)
      else n.add(k)
      return n
    })

  const selfFeedback = node.eval_prompts.flatMap((q) =>
    q.rubric_points.map((point, i) => ({
      prompt_id: q.id,
      point,
      idx: i,
      covered: covered.has(`${q.id}::${i}`),
    })),
  )
  const previewScore = scoreFromFeedback(selfFeedback)

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
        <span className="inline-flex min-w-0 flex-1 items-center gap-2">
          <EyeOff size={14} className="shrink-0" />
          <span className="break-words">
            Historia oculta: responde de memoria, con tus propias palabras. Aprobar requiere{' '}
            {PASS_SCORE.toFixed(1)} o más.
          </span>
        </span>
        <div className="flex flex-wrap items-center gap-1.5">
          <select
            aria-label="Estilo de preguntas"
            value={questionStyle}
            onChange={(e) => setQuestionStyle(e.target.value as QuestionStyle)}
            className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
          >
            <option value="direct">Estilo: Directas (examen)</option>
            <option value="scenario">Estilo: Caso aplicado</option>
          </select>
          <button
            type="button"
            disabled={busy || regeneratingQuestions}
            onClick={handleRegenerateQuestions}
            title="Genera nuevas preguntas evaluando la misma rúbrica"
            className="inline-flex shrink-0 items-center gap-1.5 rounded border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <RefreshCw size={12} className={regeneratingQuestions ? 'animate-spin' : ''} />
            {regeneratingQuestions ? 'Generando preguntas...' : 'Nuevas preguntas (IA)'}
          </button>
        </div>
      </div>

      {regeneratingQuestions && (
        <div
          role="status"
          className="flex items-center gap-2 rounded-md border border-indigo-200 bg-indigo-50/70 px-3 py-2 text-xs text-indigo-950 dark:border-indigo-800/70 dark:bg-indigo-950/40 dark:text-indigo-200"
        >
          <Loader2 size={14} className="shrink-0 animate-spin text-indigo-600 dark:text-indigo-400" />
          <span>
            Formulando nuevas preguntas socráticas aplicadas para evaluar los mismos criterios de este nodo...
          </span>
        </div>
      )}

      {phase === 'answering' && (
        <>
          {isLanguageStudio && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-teal-200 bg-teal-50/60 px-3 py-2 text-xs text-teal-950 dark:border-teal-800/70 dark:bg-teal-950/35 dark:text-teal-200">
              <div className="inline-flex items-center gap-1.5 font-semibold">
                <GraduationCap size={14} className="shrink-0 text-teal-600 dark:text-teal-400" />
                <span>Nivel de apoyo:</span>
              </div>
              <div
                className="inline-flex flex-wrap rounded-md border border-teal-300 bg-white p-0.5 dark:border-teal-700 dark:bg-slate-900"
                role="radiogroup"
                aria-label="Nivel de apoyo Language Studio"
              >
                {SUPPORT_LEVELS.map((lvl) => (
                  <button
                    key={lvl.id}
                    type="button"
                    role="radio"
                    aria-checked={supportLevel === lvl.id}
                    title={lvl.detail}
                    onClick={() => setSupportLevel(lvl.id)}
                    className={`rounded px-2.5 py-1 text-xs font-medium transition ${
                      supportLevel === lvl.id
                        ? 'bg-teal-700 text-white dark:bg-teal-500 dark:text-slate-950'
                        : 'text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                    }`}
                  >
                    {lvl.label}
                  </button>
                ))}
              </div>
              <span className="text-[11px] text-teal-800 dark:text-teal-300">
                {SUPPORT_LEVELS.find((s) => s.id === supportLevel)?.detail}
              </span>
            </div>
          )}

          {order.map((q, i) => (
            <CodeChallengeInput
              key={q.id}
              prompt={q}
              index={i}
              value={answers[q.id] ?? ''}
              onChange={(nextValue) => setAnswers((a) => ({ ...a, [q.id]: nextValue }))}
              courseId={effectiveCourseId}
              engineType={effectiveEngineType}
              supportLevel={supportLevel}
              accent={accent}
              onAccentChange={setAccent}
            />
          ))}

          {busy && (
            <div
              role="status"
              className="flex items-center gap-2 rounded-md border border-indigo-200 bg-indigo-50/70 px-3 py-2 text-xs text-indigo-950 dark:border-indigo-800/70 dark:bg-indigo-950/40 dark:text-indigo-200"
            >
              <Loader2 size={14} className="shrink-0 animate-spin text-indigo-600 dark:text-indigo-400" />
              <span>
                Evaluando tus respuestas a ciegas con el Tutor Socrático (verificando puntos de rúbrica e imprecisiones)...
              </span>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={!hasAnswer || busy || regeneratingQuestions}
              onClick={evaluateWithAi}
              className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Cpu size={15} />}
              {busy ? 'Evaluando respuestas...' : 'Evaluar con Tutor IA (7/10)'}
            </button>
            <button
              type="button"
              disabled={!hasAnswer || busy || regeneratingQuestions}
              onClick={startSelfReview}
              className="rounded-md border border-slate-300 px-3 py-2 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              Autoevaluar rúbrica manualmente
            </button>
          </div>
        </>
      )}

      {phase === 'self_review' && (
        <>
          <div className="flex items-start gap-2 rounded-md border border-sky-300 bg-sky-50 px-3 py-2 text-xs text-sky-900 dark:border-sky-800 dark:bg-sky-950/50 dark:text-sky-200">
            <Info size={14} className="mt-0.5 shrink-0" />
            <span>
              Revisión manual de rúbrica: verifica con honestidad qué criterios cubriste antes de confirmar la nota.
            </span>
          </div>
          {order.map((q) => {
            const { question: cleanQ } = sanitizeCodePrompt(
              q.question,
              q.starter_code,
              q.language,
            )
            return (
              <fieldset
                key={q.id}
                className="min-w-0 rounded-md border border-slate-200 p-3 dark:border-slate-700"
              >
                <legend className="break-words px-1 text-sm font-medium">{cleanQ}</legend>
                <p className="mb-2 whitespace-pre-wrap break-words rounded bg-slate-100 p-2 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {answers[q.id]?.trim() || 'Sin respuesta'}
                </p>
                <ul className="flex flex-col gap-1.5">
                  {q.rubric_points.map((pt, i) => {
                    const k = `${q.id}::${i}`
                    const on = covered.has(k)
                    return (
                      <li key={k}>
                        <label className="flex cursor-pointer items-start gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() => toggle(k)}
                            className="mt-1"
                          />
                          <span
                            className={`inline-flex items-start gap-1 break-words ${on ? '' : 'text-slate-600 dark:text-slate-400'}`}
                          >
                            {on ? (
                              <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-500" />
                            ) : (
                              <CircleX size={14} className="mt-0.5 shrink-0 text-rose-500" />
                            )}
                            {pt}
                          </span>
                        </label>
                      </li>
                    )
                  })}
                </ul>
              </fieldset>
            )
          })}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm">
              Nota:{' '}
              <strong
                className={
                  previewScore >= PASS_SCORE
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-rose-600 dark:text-rose-400'
                }
              >
                {previewScore.toFixed(1)}
              </strong>{' '}
              / 10
            </span>
            <button
              type="button"
              onClick={() => setPhase('answering')}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
            >
              Editar respuestas
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={confirmSelfReview}
              className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
            >
              {busy && <Loader2 size={14} className="animate-spin" />}
              Confirmar nota
            </button>
          </div>
        </>
      )}

      {phase === 'result' && result && (
        <Result
          nodeTitle={node.title}
          orderedPrompts={order}
          answers={answers}
          result={result}
          now={now}
          nextNode={nextNode}
          onSelectNextNode={onSelectNextNode}
          regeneratingQuestions={regeneratingQuestions}
          onRetry={retry}
          onRegenerateQuestions={handleRegenerateQuestions}
          onBackToStory={onBackToStory}
          onAskTutor={onAskTutor}
        />
      )}
    </div>
  )
}

function Result({
  nodeTitle,
  orderedPrompts,
  answers,
  result,
  now,
  nextNode,
  onSelectNextNode,
  regeneratingQuestions,
  onRetry,
  onRegenerateQuestions,
  onBackToStory,
  onAskTutor,
}: {
  nodeTitle: string
  orderedPrompts: EvalPrompt[]
  answers: Record<string, string>
  result: EvaluateResponse
  now: number
  nextNode?: PackNode | null
  onSelectNextNode?: (nodeId: string) => void
  regeneratingQuestions: boolean
  onRetry: () => void
  onRegenerateQuestions: () => Promise<void>
  onBackToStory: () => void
  onAskTutor: (ctx: { prompt: string; banner: string; autoSend?: boolean }) => void
}) {
  const theme = useAppStore((s) => s.theme)
  const cmTheme = theme === 'dark' ? oneDark : 'light'
  const [quickQuestion, setQuickQuestion] = useState('')
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [showAll, setShowAll] = useState(false)
  const [openSolutions, setOpenSolutions] = useState<Record<string, boolean>>({})

  const p = result.progress
  const cooling = inCooldown(p, now)
  const remaining = cooling ? formatRemaining(new Date(p.next_review_at!).getTime() - now) : null
  const feedback = result.feedback
  const missed = feedback.filter((f) => !f.covered)
  const imprecisions = result.imprecisions ?? []
  const isFallback = !result.evaluated_by || result.evaluated_by === 'local_fallback'
  const reviewsById = new Map<string, PromptReviewItem>(
    (result.prompt_reviews ?? []).map((r) => [r.prompt_id, r]),
  )

  let message: string
  if (result.counted_mastery) {
    if (p.mastery_level >= MAX_MASTERY) {
      message = 'Nodo dominado (3/3). Completaste las 3 validaciones espaciadas.'
    } else if (cooling) {
      message = `Nivel ${p.mastery_level}/3 alcanzado. Próxima validación real disponible en ${remaining}.`
    } else {
      message = `Nivel ${p.mastery_level}/3 alcanzado. Ya puedes realizar la siguiente validación real.`
    }
  } else if (result.passed) {
    if (p.mastery_level >= MAX_MASTERY) {
      message = 'Nodo dominado (3/3). Práctica adicional registrada en Reps.'
    } else if (cooling) {
      message = `Práctica registrada en Reps — próxima validación real en ${remaining}.`
    } else {
      message = `Práctica registrada en Reps — el cooldown ya terminó; tu próxima aprobación contará para ${p.mastery_level + 1}/3.`
    }
  } else {
    message = `No alcanza ${PASS_SCORE.toFixed(1)}. Tu nivel (${p.mastery_level}/3) no baja; repasa lo que faltó y reintenta.`
  }

  const getQuestionStatus = (q: EvalPrompt): PromptReviewStatus => {
    const rev = reviewsById.get(q.id)
    if (rev && (rev.status === 'passed' || rev.status === 'partial' || rev.status === 'failed')) {
      return rev.status
    }
    const qFb = feedback.filter((f) => f.prompt_id === q.id)
    if (qFb.length === 0) return result.passed ? 'passed' : 'failed'
    const covCount = qFb.filter((f) => f.covered).length
    if (covCount === qFb.length) return 'passed'
    if (covCount === 0) return 'failed'
    return 'partial'
  }

  const toggleSolution = (promptId: string) => {
    setOpenSolutions((prev) => ({ ...prev, [promptId]: !prev[promptId] }))
  }

  const buildCorrectionBanner = () => {
    const missedSummary =
      missed.length > 0
        ? `Puntos faltantes: ${missed.map((m) => m.point).join('; ')}.`
        : 'Cubrí todos los puntos de la rúbrica.'
    const impSummary =
      imprecisions.length > 0 ? ` Imprecisiones: ${imprecisions.join('; ')}.` : ''
    return `Corrección en "${nodeTitle}": Nota ${result.score.toFixed(1)}/10. ${missedSummary}${impSummary}`
  }

  const safeSelectedIdx = Math.min(Math.max(0, selectedIdx), Math.max(0, orderedPrompts.length - 1))
  const visiblePrompts = showAll
    ? orderedPrompts.map((q, idx) => ({ q, idx }))
    : orderedPrompts[safeSelectedIdx]
      ? [{ q: orderedPrompts[safeSelectedIdx], idx: safeSelectedIdx }]
      : []

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div
        className={`flex items-center gap-3 rounded-md border p-3 ${
          result.passed
            ? 'border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/40'
            : 'border-rose-300 bg-rose-50 dark:border-rose-800 dark:bg-rose-950/40'
        }`}
      >
        {result.passed ? (
          <CheckCircle2 className="shrink-0 text-emerald-600 dark:text-emerald-400" />
        ) : (
          <CircleX className="shrink-0 text-rose-600 dark:text-rose-400" />
        )}
        <div className="min-w-0">
          <div className="text-lg font-semibold">
            {result.score.toFixed(1)} / 10 · {result.passed ? 'Aprobado' : 'No aprobado'}
          </div>
          <div className="break-words text-sm">{message}</div>
        </div>
      </div>

      {result.routing_suggestion && (
        <div className="flex items-start gap-2.5 rounded-md border border-indigo-200 bg-indigo-50/75 px-3 py-2.5 text-xs text-indigo-950 dark:border-indigo-800/80 dark:bg-indigo-950/40 dark:text-indigo-200">
          <Compass size={15} className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
          <div className="min-w-0">
            <span className="font-semibold uppercase tracking-wide text-indigo-700 dark:text-indigo-300">
              Siguiente paso sugerido:{' '}
            </span>
            <span className="break-words">{result.routing_suggestion}</span>
          </div>
        </div>
      )}

      {isFallback && (
        <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>
            Evaluado con el motor determinista local (no hay API key activa). Puedes configurar Groq, Gemini Free u
            Ollama en el ícono de engranaje de la barra superior.
          </span>
        </div>
      )}

      {orderedPrompts.length > 0 && (
        <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-slate-50/60 p-3 dark:border-slate-700 dark:bg-slate-800/40">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Revisión por pregunta">
              {orderedPrompts.map((q, idx) => {
                const st = getQuestionStatus(q)
                const isSelected = !showAll && idx === safeSelectedIdx
                const badgeColors =
                  st === 'passed'
                    ? 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-700/80 dark:bg-emerald-950/50 dark:text-emerald-300'
                    : st === 'partial'
                      ? 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700/80 dark:bg-amber-950/50 dark:text-amber-200'
                      : 'border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-700/80 dark:bg-rose-950/50 dark:text-rose-300'

                return (
                  <button
                    key={q.id}
                    type="button"
                    role="tab"
                    aria-selected={isSelected}
                    onClick={() => {
                      setShowAll(false)
                      setSelectedIdx(idx)
                    }}
                    className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors ${badgeColors} ${
                      isSelected
                        ? 'ring-2 ring-slate-900 dark:ring-slate-100'
                        : 'opacity-85 hover:opacity-100'
                    }`}
                  >
                    {st === 'passed' ? (
                      <CheckCircle2 size={13} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
                    ) : st === 'partial' ? (
                      <AlertTriangle size={13} className="shrink-0 text-amber-600 dark:text-amber-400" />
                    ) : (
                      <CircleX size={13} className="shrink-0 text-rose-600 dark:text-rose-400" />
                    )}
                    <span>Pregunta {idx + 1}</span>
                  </button>
                )
              })}
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              {!showAll && orderedPrompts.length > 1 && (
                <>
                  <button
                    type="button"
                    disabled={safeSelectedIdx === 0}
                    onClick={() => setSelectedIdx((i) => Math.max(0, i - 1))}
                    className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                  >
                    <ArrowLeft size={12} />
                    Anterior
                  </button>
                  <button
                    type="button"
                    disabled={safeSelectedIdx >= orderedPrompts.length - 1}
                    onClick={() => setSelectedIdx((i) => Math.min(orderedPrompts.length - 1, i + 1))}
                    className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                  >
                    Siguiente
                    <ArrowRight size={12} />
                  </button>
                </>
              )}
              {orderedPrompts.length > 1 && (
                <button
                  type="button"
                  onClick={() => setShowAll((v) => !v)}
                  className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                >
                  <Layers size={12} />
                  {showAll ? 'Revisar una a una' : 'Ver todas'}
                </button>
              )}
            </div>
          </div>

          <div className="flex flex-col gap-4">
            {visiblePrompts.map(({ q, idx }) => {
              const rev = reviewsById.get(q.id)
              const st = getQuestionStatus(q)
              const { question: cleanQuestion, starterCode: cleanStarter } = sanitizeCodePrompt(
                q.question,
                q.starter_code,
                q.language,
              )
              const studentAnswer = (answers[q.id] ?? '').trim()
              const ct = q.challenge_type ?? 'concept'
              const isCodeEditorChallenge = ct === 'debug' || ct === 'implement'
              const isTraceChallenge = ct === 'trace'
              const isLanguageChallenge =
                ct === 'fill_blank' ||
                ct === 'translate' ||
                ct === 'speaking_prompt' ||
                q.language === 'en'
              const langLabel = (q.language && q.language !== 'text' ? q.language : 'java').toUpperCase()
              const extensions = getLanguageExtension(q.language)

              const qFeedback = feedback.filter((f) => f.prompt_id === q.id)
              const rubricItems =
                qFeedback.length > 0
                  ? qFeedback
                  : q.rubric_points.map((pt, pIdx) => ({
                      prompt_id: q.id,
                      point_index: pIdx,
                      point: pt,
                      covered: st === 'passed',
                    }))

              const coveredInQ = rubricItems.filter((f) => f.covered).length
              const missedInQ = rubricItems.filter((f) => !f.covered)
              const diagnosisText =
                rev?.diagnosis ||
                (st === 'passed'
                  ? 'Respuesta correcta: cubriste con precisión todos los criterios evaluados en esta pregunta.'
                  : missedInQ.length > 0
                    ? `Faltó incorporar: ${missedInQ.map((m) => m.point).join('; ')}.`
                    : 'Revisa las observaciones técnicas para completar esta pregunta.')

              const codeFixes = rev?.code_fixes ?? []
              const correctedSolution = rev?.corrected_solution?.trim() || null
              const isSolutionOpen = Boolean(openSolutions[q.id])

              const statusBadge =
                st === 'passed'
                  ? {
                      label: 'Correcta',
                      cls: 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300',
                    }
                  : st === 'partial'
                    ? {
                        label: 'Parcial',
                        cls: 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950/60 dark:text-amber-200',
                      }
                    : {
                        label: 'Por corregir',
                        cls: 'border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-700 dark:bg-rose-950/60 dark:text-rose-300',
                      }

              return (
                <div
                  key={q.id}
                  className="flex min-w-0 flex-col gap-3 rounded-md border border-slate-200 bg-white p-3.5 dark:border-slate-700 dark:bg-slate-900/80"
                >
                  {/* 1. Enunciado exacto de la pregunta */}
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2 dark:border-slate-800">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-xs font-bold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                        Pregunta {idx + 1} de {orderedPrompts.length}
                      </span>
                      {ct !== 'concept' && (
                        <span className="inline-flex items-center gap-1 rounded border border-slate-300 bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300">
                          {ct === 'debug' ? (
                            <Bug size={11} />
                          ) : ct === 'trace' ? (
                            <Terminal size={11} />
                          ) : ct === 'fill_blank' ? (
                            <PenLine size={11} />
                          ) : ct === 'translate' ? (
                            <Languages size={11} />
                          ) : ct === 'speaking_prompt' ? (
                            <Mic size={11} />
                          ) : (
                            <Code2 size={11} />
                          )}
                          {ct === 'fill_blank'
                            ? 'Completar'
                            : ct === 'translate'
                              ? 'Redactar en inglés'
                              : ct === 'speaking_prompt'
                                ? 'Speaking'
                                : ct}{' '}
                          · {langLabel}
                        </span>
                      )}
                    </div>
                    <span
                      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] font-semibold ${statusBadge.cls}`}
                    >
                      {st === 'passed' ? (
                        <CheckCircle2 size={12} />
                      ) : st === 'partial' ? (
                        <AlertTriangle size={12} />
                      ) : (
                        <CircleX size={12} />
                      )}
                      {statusBadge.label} ({coveredInQ}/{rubricItems.length} criterios)
                    </span>
                  </div>

                  <div className="break-words text-sm font-medium text-slate-900 dark:text-slate-100">
                    {cleanQuestion}
                  </div>

                  {isTraceChallenge && cleanStarter && (
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                        Código trazado
                      </span>
                      <div className="overflow-hidden rounded-md border border-slate-300 text-xs dark:border-slate-700">
                        <CodeMirror
                          value={cleanStarter}
                          editable={false}
                          readOnly={true}
                          theme={cmTheme}
                          extensions={extensions}
                          basicSetup={{
                            lineNumbers: true,
                            foldGutter: false,
                            highlightActiveLine: false,
                          }}
                        />
                      </div>
                    </div>
                  )}

                  {/* 2. Tu respuesta */}
                  <div className="flex flex-col gap-1">
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      Tu respuesta
                    </span>
                    {isCodeEditorChallenge ? (
                      <div className="overflow-hidden rounded-md border border-slate-300 text-xs dark:border-slate-700">
                        <CodeMirror
                          value={studentAnswer || cleanStarter || '// Sin respuesta'}
                          editable={false}
                          readOnly={true}
                          theme={cmTheme}
                          extensions={extensions}
                          basicSetup={{
                            lineNumbers: true,
                            foldGutter: false,
                            highlightActiveLine: false,
                          }}
                        />
                      </div>
                    ) : (
                      <div className="whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-slate-50 p-2.5 text-xs text-slate-800 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-200">
                        {studentAnswer || 'Sin respuesta registrada.'}
                      </div>
                    )}
                  </div>

                  {/* 3. Puntos de rubrica solo de esa pregunta */}
                  <div className="flex flex-col gap-1.5">
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      Rúbrica de esta pregunta ({coveredInQ}/{rubricItems.length})
                    </span>
                    <ul className="flex flex-col gap-1 text-xs">
                      {rubricItems.map((item) => (
                        <li
                          key={`${item.prompt_id}::${item.point_index}`}
                          className={`flex items-start gap-2 rounded px-2 py-1.5 break-words ${
                            item.covered
                              ? 'bg-emerald-50/70 text-emerald-950 dark:bg-emerald-950/30 dark:text-emerald-200'
                              : 'bg-rose-50/70 text-rose-950 dark:bg-rose-950/30 dark:text-rose-200'
                          }`}
                        >
                          {item.covered ? (
                            <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                          ) : (
                            <CircleX size={14} className="mt-0.5 shrink-0 text-rose-600 dark:text-rose-400" />
                          )}
                          <span>{item.point}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* 4. Diagnostico especifico de esa pregunta */}
                  <div className="rounded-md border border-slate-200 bg-slate-50/80 p-2.5 text-xs dark:border-slate-700 dark:bg-slate-800/50">
                    <div className="mb-1 font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">
                      Diagnóstico
                    </div>
                    <p className="break-words leading-relaxed text-slate-800 dark:text-slate-200">
                      {diagnosisText}
                    </p>
                  </div>

                  {/* 5. Si existen code_fixes: tarjetas de cambio puntual */}
                  {codeFixes.length > 0 && (
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-300">
                        <Wrench size={13} />
                        {isLanguageChallenge
                          ? `Correcciones puntuales (${codeFixes.length})`
                          : `Correcciones línea por línea (${codeFixes.length})`}
                      </div>
                      {codeFixes.map((fix, fIdx) => (
                        <div
                          key={fIdx}
                          className="flex flex-col gap-2 rounded-md border border-amber-200 bg-amber-50/40 p-2.5 text-xs dark:border-amber-800/70 dark:bg-amber-950/25"
                        >
                          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                            <div className="flex min-w-0 flex-col gap-1">
                              <span className="text-[11px] font-semibold text-rose-700 dark:text-rose-300">
                                {isLanguageChallenge ? 'Tu frase' : 'Tu código'}
                              </span>
                              <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded border border-rose-200 bg-rose-50/80 p-2 font-mono text-[11px] text-rose-950 dark:border-rose-800/70 dark:bg-rose-950/50 dark:text-rose-200">
                                {fix.broken_snippet}
                              </pre>
                            </div>
                            <div className="flex min-w-0 flex-col gap-1">
                              <span className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-300">
                                {isLanguageChallenge ? 'Corrección natural' : 'Cambio necesario'}
                              </span>
                              <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded border border-emerald-200 bg-emerald-50/80 p-2 font-mono text-[11px] text-emerald-950 dark:border-emerald-800/70 dark:bg-emerald-950/50 dark:text-emerald-200">
                                {fix.fixed_snippet}
                              </pre>
                            </div>
                          </div>
                          <div className="break-words text-xs text-slate-700 dark:text-slate-200">
                            <strong className="font-semibold text-slate-900 dark:text-white">
                              Por qué:{' '}
                            </strong>
                            {fix.why}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 6. Si existe corrected_solution: acordeon colapsado "Ver solucion de referencia" */}
                  {correctedSolution && (
                    <div className="flex flex-col gap-2">
                      <button
                        type="button"
                        onClick={() => toggleSolution(q.id)}
                        className="inline-flex w-fit items-center gap-1.5 rounded border border-slate-300 bg-slate-100 px-2.5 py-1.5 text-xs font-medium text-slate-800 hover:bg-slate-200/80 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
                      >
                        {isSolutionOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        {isSolutionOpen
                          ? isLanguageChallenge
                            ? 'Ocultar respuesta modelo'
                            : 'Ocultar solución de referencia'
                          : isLanguageChallenge
                            ? 'Ver respuesta modelo en inglés'
                            : 'Ver solución de referencia'}
                      </button>
                      {isSolutionOpen && (
                        <div className="rounded-md border border-slate-300 bg-slate-50 p-2.5 dark:border-slate-700 dark:bg-slate-900">
                          {isCodeEditorChallenge ? (
                            <div className="overflow-hidden rounded border border-slate-300 text-xs dark:border-slate-700">
                              <CodeMirror
                                value={correctedSolution}
                                editable={false}
                                readOnly={true}
                                theme={cmTheme}
                                extensions={extensions}
                                basicSetup={{
                                  lineNumbers: true,
                                  foldGutter: false,
                                  highlightActiveLine: false,
                                }}
                              />
                            </div>
                          ) : (
                            <MarkdownView
                              content={correctedSolution}
                              className="text-slate-800 dark:text-slate-200"
                            />
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {imprecisions.length > 0 && (
        <div>
          <div className="mb-1 text-sm font-medium">Observaciones globales del intento</div>
          <ul className="flex flex-col gap-1 text-sm text-amber-800 dark:text-amber-300">
            {imprecisions.map((imp, i) => {
              const cleanedImp = imp.replace(/^(?:q\d+|p\d+)(?:::\d+)?\s*[:\-–]\s*/i, '').trim()
              return (
                <li key={i} className="flex items-start gap-1.5 break-words">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-500" />{' '}
                  {cleanedImp || imp}
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {result.re_explanation && (
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm dark:border-slate-700 dark:bg-slate-800/60">
          <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <MessageCircle size={13} /> Re-explicación focalizada
          </div>
          <MarkdownView
            content={result.re_explanation}
            className="text-slate-700 dark:text-slate-200"
          />
        </div>
      )}

      <p className="text-[11px] text-slate-500 dark:text-slate-400">
        Evaluador: <span className="font-mono">{result.evaluated_by ?? 'local_fallback'}</span>
      </p>

      <div className="flex flex-wrap gap-2">
        {result.passed && nextNode && onSelectNextNode && (
          <button
            type="button"
            onClick={() => onSelectNextNode(nextNode.id)}
            className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-xs hover:bg-emerald-500 dark:bg-emerald-500 dark:text-slate-950 dark:hover:bg-emerald-400"
          >
            <span>Siguiente: {nextNode.title}</span>
            <ArrowRight size={16} className="shrink-0" />
          </button>
        )}
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
        >
          {result.passed ? <Shuffle size={16} /> : <RotateCcw size={16} />}
          {result.passed ? 'Practicar en orden mezclado' : 'Reintentar en orden mezclado'}
        </button>
        <button
          type="button"
          disabled={regeneratingQuestions}
          onClick={onRegenerateQuestions}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-3.5 py-2 text-sm font-medium hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800"
        >
          <RefreshCw size={15} className={regeneratingQuestions ? 'animate-spin' : ''} />
          Nuevas preguntas (IA)
        </button>
        <button
          type="button"
          onClick={onBackToStory}
          className="rounded-md border border-slate-300 px-4 py-2 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800"
        >
          Volver a la historia
        </button>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          const q = quickQuestion.trim()
          if (!q) return
          setQuickQuestion('')
          onAskTutor({
            prompt: q,
            banner: buildCorrectionBanner(),
            autoSend: true,
          })
        }}
        className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50/70 p-2 dark:border-slate-700 dark:bg-slate-800/50"
      >
        <MessageSquare size={15} className="ml-1 shrink-0 text-slate-500 dark:text-slate-400" />
        <input
          type="text"
          value={quickQuestion}
          onChange={(e) => setQuickQuestion(e.target.value)}
          placeholder="¿Alguna duda sobre este tema? Pregúntale al tutor..."
          className="min-w-0 flex-1 rounded border border-slate-300 bg-white px-2.5 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:border-slate-600 dark:bg-slate-900"
        />
        <button
          type="submit"
          disabled={!quickQuestion.trim()}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-40 dark:bg-indigo-500 dark:hover:bg-indigo-400"
        >
          <Send size={13} />
          Enviar
        </button>
      </form>
    </div>
  )
}
