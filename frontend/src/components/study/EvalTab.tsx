import { useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, CircleX, EyeOff, Info, RotateCcw, Shuffle } from 'lucide-react'
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
import { formatRemaining, useNow } from './studyUtils'

interface Props {
  node: PackNode
  progress: NodeProgress
  onSubmit: (req: { answers: { prompt_id: string; text: string }[]; covered_points: string[] }) => Promise<EvaluateResponse>
  onBackToStory: () => void
  /** true mientras hay respuestas/revision sin cerrar (para pedir confirmacion al salir). */
  onInProgressChange: (v: boolean) => void
}

type Phase = 'answering' | 'review' | 'result'

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

export default function EvalTab({ node, progress, onSubmit, onBackToStory, onInProgressChange }: Props) {
  const [order, setOrder] = useState(() => shuffled(node.id, node.eval_prompts))
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [phase, setPhase] = useState<Phase>('answering')
  const [covered, setCovered] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<EvaluateResponse | null>(null)
  const [busy, setBusy] = useState(false)

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

  const feedback = useMemo(
    () =>
      node.eval_prompts.flatMap((q) =>
        q.rubric_points.map((point, i) => ({
          prompt_id: q.id,
          point,
          idx: i,
          covered: covered.has(`${q.id}::${i}`),
        })),
      ),
    [node, covered],
  )
  const previewScore = scoreFromFeedback(feedback)
  const hasAnswer = Object.values(answers).some((t) => t.trim().length > 0)

  const startReview = () => {
    const auto = previewGrade(node, answers)
    setCovered(new Set(auto.filter((f) => f.covered).map((f) => `${f.prompt_id}::${f.point_index}`)))
    setPhase('review')
  }

  const confirm = async () => {
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
    setAnswers({})
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

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
        <EyeOff size={14} /> Historia oculta: responde de memoria, con tus propias palabras. Aprobar requiere {PASS_SCORE.toFixed(1)} o más.
      </div>

      {phase === 'answering' && (
        <>
          {order.map((q, i) => (
            <label key={q.id} className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">
                {i + 1}. {q.question}
              </span>
              <textarea
                value={answers[q.id] ?? ''}
                onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                rows={4}
                className="rounded-md border border-slate-300 bg-white p-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 dark:border-slate-600 dark:bg-slate-900"
                placeholder="Tu respuesta..."
              />
            </label>
          ))}
          <button
            type="button"
            disabled={!hasAnswer}
            onClick={startReview}
            className="self-start rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
          >
            Enviar respuestas
          </button>
        </>
      )}

      {phase === 'review' && (
        <>
          <div className="flex items-start gap-2 rounded-md border border-sky-300 bg-sky-50 px-3 py-2 text-xs text-sky-900 dark:border-sky-800 dark:bg-sky-950/50 dark:text-sky-200">
            <Info size={14} className="mt-0.5 shrink-0" />
            <span>
              Evaluador demo local — en v1.0 evalúa el tutor IA. Detecta palabras clave y puede equivocarse: corrige los puntos
              con honestidad antes de confirmar.
            </span>
          </div>
          {order.map((q) => (
            <fieldset key={q.id} className="rounded-md border border-slate-200 p-3 dark:border-slate-700">
              <legend className="px-1 text-sm font-medium">{q.question}</legend>
              <p className="mb-2 whitespace-pre-wrap rounded bg-slate-100 p-2 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {answers[q.id]?.trim() || 'Sin respuesta'}
              </p>
              <ul className="flex flex-col gap-1.5">
                {q.rubric_points.map((pt, i) => {
                  const k = `${q.id}::${i}`
                  const on = covered.has(k)
                  return (
                    <li key={k}>
                      <label className="flex cursor-pointer items-start gap-2 text-sm">
                        <input type="checkbox" checked={on} onChange={() => toggle(k)} className="mt-1" />
                        <span className={`inline-flex items-start gap-1 ${on ? '' : 'text-slate-600 dark:text-slate-400'}`}>
                          {on ? <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-emerald-500" /> : <CircleX size={14} className="mt-0.5 shrink-0 text-rose-500" />}
                          {pt}
                        </span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            </fieldset>
          ))}
          <div className="flex items-center gap-3">
            <span className="text-sm">
              Nota: <strong className={previewScore >= PASS_SCORE ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}>{previewScore.toFixed(1)}</strong> / 10
            </span>
            <button type="button" onClick={() => setPhase('answering')} className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800">
              Editar respuestas
            </button>
            <button type="button" disabled={busy} onClick={confirm} className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300">
              Confirmar nota
            </button>
          </div>
        </>
      )}

      {phase === 'result' && result && (
        <Result
          result={result}
          feedback={feedback}
          now={now}
          onRetry={retry}
          onBackToStory={onBackToStory}
        />
      )}
    </div>
  )
}

function Result({
  result,
  feedback,
  now,
  onRetry,
  onBackToStory,
}: {
  result: EvaluateResponse
  feedback: { point: string; covered: boolean }[]
  now: number
  onRetry: () => void
  onBackToStory: () => void
}) {
  const p = result.progress
  const cooling = inCooldown(p, now)
  const remaining = cooling ? formatRemaining(new Date(p.next_review_at!).getTime() - now) : null
  const coveredPoints = feedback.filter((f) => f.covered)
  const missed = feedback.filter((f) => !f.covered)

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

  return (
    <div className="flex flex-col gap-4">
      <div className={`flex items-center gap-3 rounded-md border p-3 ${result.passed ? 'border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/40' : 'border-rose-300 bg-rose-50 dark:border-rose-800 dark:bg-rose-950/40'}`}>
        {result.passed ? <CheckCircle2 className="shrink-0 text-emerald-600 dark:text-emerald-400" /> : <CircleX className="shrink-0 text-rose-600 dark:text-rose-400" />}
        <div>
          <div className="text-lg font-semibold">{result.score.toFixed(1)} / 10 · {result.passed ? 'Aprobado' : 'No aprobado'}</div>
          <div className="text-sm">{message}</div>
        </div>
      </div>

      {coveredPoints.length > 0 && (
        <div>
          <div className="mb-1 text-sm font-medium">Puntos cubiertos ({coveredPoints.length}/{feedback.length})</div>
          <ul className="flex flex-col gap-1 text-sm text-slate-700 dark:text-slate-300">
            {coveredPoints.map((c, i) => (
              <li key={i} className="flex items-start gap-1.5">
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
              <li key={i} className="flex items-start gap-1.5">
                <CircleX size={14} className="mt-0.5 shrink-0 text-rose-500" /> {m.point}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-[11px] text-slate-500 dark:text-slate-400">
        Evaluador demo local — en v1.0 evalúa el tutor IA.
      </p>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={onRetry} className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300">
          {result.passed ? <Shuffle size={16} /> : <RotateCcw size={16} />}
          {result.passed ? 'Practicar en orden mezclado' : 'Reintentar en orden mezclado'}
        </button>
        <button type="button" onClick={onBackToStory} className="rounded-md border border-slate-300 px-4 py-2 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800">
          Volver a la historia
        </button>
      </div>
    </div>
  )
}
