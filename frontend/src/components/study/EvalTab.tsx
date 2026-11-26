import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleX,
  Cpu,
  EyeOff,
  Info,
  Loader2,
  MessageCircle,
  MessageSquare,
  RefreshCw,
  RotateCcw,
  Send,
  Shuffle,
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
} from '../../api/study'
import type { QuestionStyle } from '../../api/curriculum'
import { useStudyStore } from '../../store/useStudyStore'
import MarkdownView from '../common/MarkdownView'
import CodeChallengeInput from './CodeChallengeInput'
import { formatRemaining, useNow } from './studyUtils'

interface Props {
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
      init[p.id] = p.starter_code
    }
  }
  return init
}

function isPromptEditedOrAnswered(q: EvalPrompt, answers: Record<string, string>): boolean {
  const val = (answers[q.id] ?? '').trim()
  if (val.length === 0) return false
  if ((q.challenge_type === 'debug' || q.challenge_type === 'implement') && q.starter_code) {
    return val !== q.starter_code.trim()
  }
  return true
}

export default function EvalTab({
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
          {order.map((q, i) => (
            <CodeChallengeInput
              key={q.id}
              prompt={q}
              index={i}
              value={answers[q.id] ?? ''}
              onChange={(nextValue) => setAnswers((a) => ({ ...a, [q.id]: nextValue }))}
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
          {order.map((q) => (
            <fieldset
              key={q.id}
              className="min-w-0 rounded-md border border-slate-200 p-3 dark:border-slate-700"
            >
              <legend className="break-words px-1 text-sm font-medium">{q.question}</legend>
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
          ))}
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
  const [quickQuestion, setQuickQuestion] = useState('')
  const p = result.progress
  const cooling = inCooldown(p, now)
  const remaining = cooling ? formatRemaining(new Date(p.next_review_at!).getTime() - now) : null
  const feedback = result.feedback
  const coveredPoints = feedback.filter((f) => f.covered)
  const missed = feedback.filter((f) => !f.covered)
  const imprecisions = result.imprecisions ?? []
  const isFallback = !result.evaluated_by || result.evaluated_by === 'local_fallback'

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

  const buildCorrectionBanner = () => {
    const missedSummary =
      missed.length > 0
        ? `Puntos faltantes: ${missed.map((m) => m.point).join('; ')}.`
        : 'Cubrí todos los puntos de la rúbrica.'
    const impSummary =
      imprecisions.length > 0 ? ` Imprecisiones: ${imprecisions.join('; ')}.` : ''
    return `Corrección en "${nodeTitle}": Nota ${result.score.toFixed(1)}/10. ${missedSummary}${impSummary}`
  }

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

      {isFallback && (
        <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>
            Evaluado con el motor determinista local (no hay API key activa). Puedes configurar Groq, Gemini Free u
            Ollama en el ícono de engranaje de la barra superior.
          </span>
        </div>
      )}

      {coveredPoints.length > 0 && (
        <div>
          <div className="mb-1 text-sm font-medium">
            Puntos acertados ({coveredPoints.length}/{feedback.length})
          </div>
          <ul className="flex flex-col gap-1 text-sm text-slate-700 dark:text-slate-300">
            {coveredPoints.map((c, i) => (
              <li key={i} className="flex items-start gap-1.5 break-words">
                <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-500" /> {c.point}
              </li>
            ))}
          </ul>
        </div>
      )}

      {missed.length > 0 && (
        <div>
          <div className="mb-1 text-sm font-medium">Qué faltó</div>
          <ul className="flex flex-col gap-1 text-sm text-slate-700 dark:text-slate-300">
            {missed.map((m, i) => (
              <li key={i} className="flex items-start gap-1.5 break-words">
                <CircleX size={14} className="mt-0.5 shrink-0 text-rose-500" /> {m.point}
              </li>
            ))}
          </ul>
        </div>
      )}

      {imprecisions.length > 0 && (
        <div>
          <div className="mb-1 text-sm font-medium">Imprecisiones detectadas</div>
          <ul className="flex flex-col gap-1 text-sm text-amber-800 dark:text-amber-300">
            {imprecisions.map((imp, i) => (
              <li key={i} className="flex items-start gap-1.5 break-words">
                <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-500" /> {imp}
              </li>
            ))}
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
