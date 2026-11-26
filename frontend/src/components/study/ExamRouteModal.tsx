import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Clock,
  FlaskConical,
  Loader2,
  MessageSquare,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  Sprout,
  X,
  Zap,
} from 'lucide-react'
import {
  generateExamRoute,
  getExamRoute,
  type CooldownMode,
  type CourseTree,
  type ExamRouteResponse,
  type ExamRouteStep,
} from '../../api/study'

interface Props {
  open: boolean
  onClose: () => void
  tree: CourseTree
  cooldownMode: CooldownMode
  onChangeCooldownMode: (mode: CooldownMode) => void
  onSelectNode: (nodeId: string) => void
  onAskTutor: (ctx: { prompt: string; banner: string; autoSend?: boolean }) => void
  onRouteUpdated?: (route: ExamRouteResponse) => void
}

function defaultExamDate(): string {
  const d = new Date()
  d.setDate(d.getDate() + 5)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const ACTION_LABEL: Record<string, string> = {
  study_and_eval: 'Historia + Eval',
  spaced_review: 'Repaso espaciado',
  practice_exam: 'Simulacro práctico',
  custom: 'Refuerzo',
}

export default function ExamRouteModal({
  open,
  onClose,
  tree,
  cooldownMode,
  onChangeCooldownMode,
  onSelectNode,
  onAskTutor,
  onRouteUpdated,
}: Props) {
  const [route, setRoute] = useState<ExamRouteResponse | null>(null)
  const [loadingInitial, setLoadingInitial] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(true)

  const [examDate, setExamDate] = useState(defaultExamDate)
  const [hoursPerDay, setHoursPerDay] = useState(3)
  const [goal, setGoal] = useState('')
  const [examTopics, setExamTopics] = useState('')

  useEffect(() => {
    if (!open) return
    let active = true
    setError(null)
    setLoadingInitial(true)
    void getExamRoute(tree.course_id)
      .then((saved) => {
        if (!active) return
        if (saved) {
          setRoute(saved)
          setExamDate(saved.exam_date)
          setHoursPerDay(saved.hours_per_day)
          setGoal(saved.goal)
          setExamTopics(saved.exam_topics)
          setShowForm(false)
          onRouteUpdated?.(saved)
        } else {
          setRoute(null)
          setShowForm(true)
        }
      })
      .catch((err: unknown) => {
        if (!active) return
        setError(err instanceof Error ? err.message : 'No se pudo cargar la ruta guardada.')
      })
      .finally(() => {
        if (active) setLoadingInitial(false)
      })
    return () => {
      active = false
    }
  }, [open, tree.course_id])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setGenerating(true)
    try {
      const created = await generateExamRoute(tree.course_id, {
        exam_date: examDate,
        hours_per_day: Number(hoursPerDay) || 3,
        goal: goal.trim(),
        exam_topics: examTopics.trim(),
      })
      setRoute(created)
      setShowForm(false)
      onRouteUpdated?.(created)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'No se pudo generar la ruta de examen.')
    } finally {
      setGenerating(false)
    }
  }

  const renderStep = (step: ExamRouteStep, idx: number) => {
    const progress = step.node_id ? tree.progress[step.node_id] : undefined
    const curMastery = progress?.mastery_level ?? 0
    const isDone = Boolean(step.node_id && curMastery >= step.target_mastery)
    const isPractice = step.branch === 'practice' || step.action === 'practice_exam'
    const actionLabel = ACTION_LABEL[step.action] ?? 'Estudio dirigido'

    return (
      <div
        key={`${step.node_id ?? step.node_title}-${idx}`}
        className={`flex flex-wrap items-start justify-between gap-2.5 rounded-md border p-2.5 text-xs ${
          isDone
            ? 'border-emerald-300/80 bg-emerald-50/50 dark:border-emerald-800/70 dark:bg-emerald-950/25'
            : isPractice
              ? 'border-amber-300/80 bg-amber-50/40 dark:border-amber-800/70 dark:bg-amber-950/20'
              : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/70'
        }`}
      >
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-1.5">
            {isDone ? (
              <CheckCircle2 size={14} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
            ) : isPractice ? (
              <FlaskConical size={13} className="shrink-0 text-amber-600 dark:text-amber-400" />
            ) : (
              <Sprout size={13} className="shrink-0 text-indigo-600 dark:text-indigo-400" />
            )}
            <span className={`font-semibold ${isDone ? 'line-through opacity-75' : ''}`}>
              {step.node_title}
            </span>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {actionLabel}
            </span>
            <span className="inline-flex items-center gap-0.5 font-mono text-[10px] text-slate-500 dark:text-slate-400">
              <Clock size={10} />
              {step.estimated_minutes} min
            </span>
            {step.node_id && (
              <span className="rounded bg-indigo-50 px-1.5 py-0.5 font-mono text-[10px] font-medium text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">
                {curMastery}/3 → meta {step.target_mastery}/3
              </span>
            )}
          </div>
          {step.reason && (
            <p className="text-[11px] leading-snug text-slate-600 dark:text-slate-300">
              {step.reason}
            </p>
          )}
        </div>

        {step.node_id && (
          <button
            type="button"
            onClick={() => {
              onSelectNode(step.node_id as string)
              onClose()
            }}
            className="inline-flex shrink-0 items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1.5 text-[11px] font-semibold text-white hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400"
          >
            Ir al nodo <ArrowRight size={12} />
          </button>
        )}
      </div>
    )
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-3 sm:p-5"
      role="dialog"
      aria-modal="true"
      aria-labelledby="exam-route-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-950">
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <div className="flex min-w-0 items-center gap-2">
            <CalendarClock size={18} className="shrink-0 text-indigo-600 dark:text-indigo-400" />
            <div className="min-w-0">
              <h2 id="exam-route-title" className="truncate text-sm font-semibold">
                Ruta de preparación para examen · {tree.title}
              </h2>
              <p className="truncate text-xs text-slate-500 dark:text-slate-400">
                Plan diario basado en tu árbol real, tus prerrequisitos y tu avance actual 0/3 → 3/3.
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {route && (
              <button
                type="button"
                onClick={() => setShowForm((v) => !v)}
                className="inline-flex items-center gap-1 rounded border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
              >
                <SlidersHorizontal size={12} />
                {showForm ? 'Ocultar ajustes' : 'Ajustar / Regenerar'}
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              aria-label="Cerrar ruta de examen"
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <X size={16} />
            </button>
          </div>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {loadingInitial && (
            <div className="flex items-center gap-2 py-8 text-sm text-slate-500">
              <Loader2 size={16} className="animate-spin" />
              Cargando ruta guardada...
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-800 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200"
            >
              {error}
            </div>
          )}

          {!loadingInitial && showForm && (
            <form
              onSubmit={(e) => void handleGenerate(e)}
              className="space-y-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3.5 dark:border-slate-800 dark:bg-slate-900/50"
            >
              <div className="grid gap-3 sm:grid-cols-3">
                <label className="flex flex-col gap-1 text-xs font-medium">
                  <span>Fecha del examen</span>
                  <input
                    type="date"
                    required
                    value={examDate}
                    onChange={(e) => setExamDate(e.target.value)}
                    className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
                  />
                </label>

                <label className="flex flex-col gap-1 text-xs font-medium">
                  <span>Horas disponibles / día</span>
                  <input
                    type="number"
                    min={0.5}
                    max={14}
                    step={0.5}
                    required
                    value={hoursPerDay}
                    onChange={(e) => setHoursPerDay(Number(e.target.value))}
                    className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
                  />
                </label>

                <label className="flex flex-col gap-1 text-xs font-medium">
                  <span>Objetivo / nota (opcional)</span>
                  <input
                    type="text"
                    value={goal}
                    onChange={(e) => setGoal(e.target.value)}
                    placeholder="Ej. Necesito 3.2 para aprobar con 4.0"
                    className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
                  />
                </label>
              </div>

              <label className="flex flex-col gap-1 text-xs font-medium">
                <span>Temario oficial del examen (opcional — la IA prioriza y detecta vacíos)</span>
                <textarea
                  rows={3}
                  value={examTopics}
                  onChange={(e) => setExamTopics(e.target.value)}
                  placeholder="Pega aquí la lista de temas o unidades del examen para cruzarla contra tu árbol actual..."
                  className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs dark:border-slate-700 dark:bg-slate-950"
                />
              </label>

              <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                <span className="text-[11px] text-slate-500 dark:text-slate-400">
                  La ruta se guarda localmente en SQLite y actualiza el avance de cada nodo en vivo.
                </span>
                <button
                  type="submit"
                  disabled={generating}
                  className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50 dark:bg-indigo-500 dark:hover:bg-indigo-400"
                >
                  {generating ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : route ? (
                    <RefreshCw size={14} />
                  ) : (
                    <Sparkles size={14} />
                  )}
                  {generating
                    ? 'Construyendo ruta...'
                    : route
                      ? 'Regenerar ruta con IA'
                      : 'Generar ruta de examen'}
                </button>
              </div>
            </form>
          )}

          {!loadingInitial && route && (
            <div className="space-y-4">
              <div className="rounded-lg border border-indigo-200 bg-indigo-50/70 p-3.5 dark:border-indigo-800/70 dark:bg-indigo-950/35">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-indigo-950 dark:text-indigo-100">
                    <span>
                      Examen: {route.exam_date} ·{' '}
                      {route.days_left === 0
                        ? 'Hoy'
                        : route.days_left === 1
                          ? 'Falta 1 día'
                          : `Faltan ${route.days_left} días`}
                    </span>
                    <span className="rounded bg-white/80 px-1.5 py-0.5 font-mono text-[10px] text-indigo-700 dark:bg-slate-900/70 dark:text-indigo-300">
                      {route.hours_per_day} h/día
                    </span>
                    <span className="rounded bg-white/80 px-1.5 py-0.5 text-[10px] font-normal text-slate-600 dark:bg-slate-900/70 dark:text-slate-300">
                      Generado por: {route.provider}
                    </span>
                  </div>

                  {route.recommended_cooldown_mode === 'urgency' && cooldownMode !== 'urgency' && (
                    <button
                      type="button"
                      onClick={() => onChangeCooldownMode('urgency')}
                      className="inline-flex items-center gap-1 rounded-md bg-slate-900 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
                    >
                      <Zap size={12} />
                      Activar Repaso Rápido (examen)
                    </button>
                  )}
                </div>
                <p className="mt-2 text-xs leading-relaxed text-indigo-950/90 dark:text-indigo-100/90">
                  {route.strategy_summary}
                </p>
              </div>

              {route.uncovered_topics.length > 0 && (
                <div className="rounded-lg border border-amber-300 bg-amber-50/80 p-3 dark:border-amber-800 dark:bg-amber-950/30">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-950 dark:text-amber-200">
                      <AlertTriangle size={14} className="shrink-0 text-amber-600 dark:text-amber-400" />
                      Temas del examen no detectados en tu árbol actual ({route.uncovered_topics.length})
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        onClose()
                        onAskTutor({
                          prompt: `Estos temas entran en mi examen pero no aparecen en mi árbol actual: ${route.uncovered_topics.join(', ')}. Ayúdame a cubrirlos con una explicación clara y preguntas de práctica.`,
                          banner: `Cubriendo temas faltantes de la ruta de examen (${route.exam_date}).`,
                          autoSend: true,
                        })
                      }}
                      className="inline-flex items-center gap-1 rounded border border-amber-400 bg-white px-2 py-1 text-[11px] font-medium text-amber-900 hover:bg-amber-100 dark:border-amber-700 dark:bg-slate-900 dark:text-amber-200 dark:hover:bg-amber-950"
                    >
                      <MessageSquare size={12} />
                      Repasar con el Tutor
                    </button>
                  </div>
                  <ul className="mt-2 flex flex-wrap gap-1.5">
                    {route.uncovered_topics.map((topic, idx) => (
                      <li
                        key={idx}
                        className="rounded border border-amber-300/80 bg-white/80 px-2 py-0.5 text-[11px] text-amber-950 dark:border-amber-800 dark:bg-slate-900/70 dark:text-amber-200"
                      >
                        {topic}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="space-y-3">
                {route.days.map((day, dIdx) => {
                  const totalMin = day.steps.reduce((acc, s) => acc + (s.estimated_minutes || 0), 0)
                  return (
                    <section
                      key={`${day.date}-${dIdx}`}
                      className="rounded-lg border border-slate-200 p-3 dark:border-slate-800"
                    >
                      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                        <div>
                          <h3 className="text-xs font-semibold text-slate-900 dark:text-slate-100">
                            {day.day_label}
                          </h3>
                          <p className="text-[11px] text-slate-500 dark:text-slate-400">
                            {day.focus}
                          </p>
                        </div>
                        <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">
                          ~{totalMin} min · {day.steps.length}{' '}
                          {day.steps.length === 1 ? 'bloque' : 'bloques'}
                        </span>
                      </div>
                      <div className="space-y-2">{day.steps.map(renderStep)}</div>
                    </section>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
