import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowDown,
  ArrowRight,
  CheckCircle2,
  ChevronLeft,
  Code2,
  Cpu,
  Database,
  GitBranch,
  HelpCircle,
  Layers,
  Loader2,
  RefreshCw,
  Terminal,
  X,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import type {
  NodeStoryboardResponse,
  StoryboardStep,
  StoryboardStreamProgress,
  StoryboardVariant,
} from '../../api/study'

export const STORYBOARD_VARIANT_META: Record<
  StoryboardVariant,
  { label: string; Icon: LucideIcon }
> = {
  execution_trace: { label: 'Traza en memoria', Icon: Cpu },
  oop_dispatch: { label: 'Despacho OOP', Icon: GitBranch },
  error_contrast: { label: 'Error -> Corrección', Icon: AlertTriangle },
  data_structure: { label: 'Estructura de datos', Icon: Layers },
  sql_pipeline: { label: 'Pipeline SQL', Icon: Database },
}

export interface CodeScenePlayerProps {
  courseId: string
  nodeId: string
  initialStoryboard: NodeStoryboardResponse | null
  generating: boolean
  progress: StoryboardStreamProgress | null
  error: string | null
  onRegenerate: () => void
  onClose?: () => void
}

interface CheckpointAnswerState {
  selectedIndex: number | null
  skipped: boolean
}

// ---------------- Helpers defensivos para state heterogeneo ----------------

function asRecord(val: unknown): Record<string, unknown> {
  if (val && typeof val === 'object' && !Array.isArray(val)) {
    return val as Record<string, unknown>
  }
  return {}
}

function asArray(val: unknown): unknown[] {
  return Array.isArray(val) ? val : []
}

function asStr(val: unknown, fallback = ''): string {
  if (val === null || val === undefined) return fallback
  if (typeof val === 'string') return val
  if (typeof val === 'number' || typeof val === 'boolean') return String(val)
  try {
    return JSON.stringify(val)
  } catch {
    return fallback
  }
}

function asNum(val: unknown): number | null {
  if (typeof val === 'number' && Number.isFinite(val)) return val
  if (typeof val === 'string' && val.trim() !== '') {
    const parsed = Number(val)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function asBool(val: unknown): boolean {
  return val === true || val === 'true' || val === 1
}

function formatAddr(raw: string): string {
  const clean = raw.trim()
  if (!clean) return ''
  return clean.startsWith('@') ? clean : `@${clean}`
}

function defaultStageLabel(stage?: StoryboardStreamProgress['stage']): string {
  switch (stage) {
    case 'analyzing':
      return 'Analizando explicación y eligiendo visualización...'
    case 'generating':
      return 'Construyendo pasos y estado en memoria...'
    case 'validating':
      return 'Validando traza y checkpoints...'
    case 'done':
      return 'Ejemplo paso a paso listo'
    default:
      return 'Analizando explicación y eligiendo visualización...'
  }
}

function stageCeiling(stage?: StoryboardStreamProgress['stage']): number {
  switch (stage) {
    case 'analyzing':
      return 48
    case 'generating':
      return 82
    case 'validating':
      return 96
    case 'done':
      return 100
    default:
      return 45
  }
}

export default function CodeScenePlayer({
  courseId,
  nodeId,
  initialStoryboard,
  generating,
  progress,
  error,
  onRegenerate,
  onClose,
}: CodeScenePlayerProps) {
  const [stepIdx, setStepIdx] = useState(0)
  const [codeViewTab, setCodeViewTab] = useState<'broken' | 'fixed'>('broken')
  const [checkpointAnswers, setCheckpointAnswers] = useState<
    Record<number, CheckpointAnswerState>
  >({})
  const [displayPct, setDisplayPct] = useState(0)

  const storyboard = initialStoryboard
  const steps = storyboard?.steps ?? []
  const safeStepIdx = steps.length > 0 ? Math.min(stepIdx, steps.length - 1) : 0
  const currentStep: StoryboardStep | undefined = steps[safeStepIdx]

  // Resetear estado local al cambiar nodo o recibir nuevo storyboard
  useEffect(() => {
    setStepIdx(0)
    setCheckpointAnswers({})
    setCodeViewTab('broken')
  }, [courseId, nodeId, storyboard?.updated_at])

  // Sincronizar pestaña de codigo en variante error_contrast segun el paso activo
  useEffect(() => {
    if (!storyboard || storyboard.variant !== 'error_contrast') {
      setCodeViewTab('broken')
      return
    }
    const stepState = asRecord(currentStep?.state)
    const view = asStr(stepState.code_view).toLowerCase()
    const phase = asStr(stepState.phase).toLowerCase()
    if ((view === 'fixed' || phase === 'fixed_diff') && storyboard.fixed_code) {
      setCodeViewTab('fixed')
    } else {
      setCodeViewTab('broken')
    }
  }, [storyboard, currentStep])

  // Interpolacion fluida del % de generacion sin retroceder ni superar el techo de etapa
  useEffect(() => {
    if (!generating) {
      if (storyboard) setDisplayPct(100)
      return
    }
    setDisplayPct((prev) => {
      const incoming = progress?.pct ?? 6
      return prev >= 100 ? Math.max(6, Math.round(incoming)) : Math.max(prev, Math.round(incoming))
    })
  }, [generating, progress?.pct, storyboard])

  useEffect(() => {
    if (!generating) return
    const ceiling = stageCeiling(progress?.stage)
    const id = window.setInterval(() => {
      setDisplayPct((prev) => {
        const floor = Math.round(progress?.pct ?? 6)
        const base = Math.max(prev, floor)
        if (base < ceiling) return base + 1
        return base
      })
    }, 420)
    return () => window.clearInterval(id)
  }, [generating, progress?.stage, progress?.pct])

  const hasFixedCode = Boolean(storyboard?.fixed_code && storyboard.fixed_code.trim().length > 0)
  const displayedCode = useMemo(() => {
    if (!storyboard) return ''
    if (storyboard.variant === 'error_contrast' && codeViewTab === 'fixed' && hasFixedCode) {
      return storyboard.fixed_code ?? storyboard.source_code
    }
    return storyboard.source_code
  }, [storyboard, codeViewTab, hasFixedCode])

  const codeLines = useMemo(
    () => displayedCode.replace(/\r\n/g, '\n').split('\n'),
    [displayedCode],
  )

  const activeLinesSet = useMemo(
    () => new Set<number>(currentStep?.active_lines ?? []),
    [currentStep],
  )

  // Vista de generacion en progreso
  if (generating) {
    const label = progress?.label?.trim() || defaultStageLabel(progress?.stage)
    const stageOrder: StoryboardStreamProgress['stage'][] = ['analyzing', 'generating', 'validating']
    const activeStageIdx = Math.max(0, stageOrder.indexOf(progress?.stage ?? 'analyzing'))

    return (
      <section
        aria-live="polite"
        className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-3.5 text-slate-900 dark:border-indigo-800/70 dark:bg-indigo-950/30 dark:text-slate-100"
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <Loader2
              size={16}
              className="shrink-0 animate-spin text-indigo-600 dark:text-indigo-400"
            />
            <span className="truncate text-xs font-medium text-slate-800 dark:text-slate-200">
              {label}
            </span>
          </div>
          <span className="shrink-0 font-mono text-xs font-semibold tabular-nums text-indigo-700 dark:text-indigo-300">
            {Math.min(100, Math.max(0, displayPct))}%
          </span>
        </div>

        <div className="mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-indigo-100 dark:bg-slate-800">
          <div
            className="h-full rounded-full bg-indigo-600 transition-all duration-300 ease-out dark:bg-indigo-400"
            style={{ width: `${Math.min(100, Math.max(4, displayPct))}%` }}
          />
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11px]">
          {[
            { id: 'analyzing', text: '1. Analizando explicación' },
            { id: 'generating', text: '2. Construyendo pasos' },
            { id: 'validating', text: '3. Validando traza' },
          ].map((st, idx) => {
            const done = idx < activeStageIdx
            const current = idx === activeStageIdx
            return (
              <span
                key={st.id}
                className={`inline-flex items-center gap-1 rounded px-2 py-0.5 font-medium ${
                  current
                    ? 'bg-indigo-600 text-white dark:bg-indigo-500'
                    : done
                      ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300'
                      : 'bg-white/70 text-slate-500 dark:bg-slate-900/60 dark:text-slate-400'
                }`}
              >
                {st.text}
              </span>
            )
          })}
        </div>
      </section>
    )
  }

  // Vista de error si fallo y no hay storyboard previo
  if (error && !storyboard) {
    return (
      <section className="rounded-lg border border-rose-300 bg-rose-50/70 p-3 text-xs text-rose-950 dark:border-rose-800/70 dark:bg-rose-950/30 dark:text-rose-200">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <AlertTriangle size={15} className="shrink-0 text-rose-600 dark:text-rose-400" />
            <span className="break-words font-medium">{error}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={onRegenerate}
              className="inline-flex items-center gap-1 rounded border border-rose-300 bg-white px-2.5 py-1 text-xs font-medium text-rose-900 hover:bg-rose-100 dark:border-rose-700 dark:bg-slate-900 dark:text-rose-200 dark:hover:bg-rose-950"
            >
              <RefreshCw size={12} /> Reintentar
            </button>
            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                <X size={12} /> Cerrar
              </button>
            )}
          </div>
        </div>
      </section>
    )
  }

  if (!storyboard || steps.length === 0 || !currentStep) {
    return null
  }

  const variantMeta =
    STORYBOARD_VARIANT_META[storyboard.variant] ?? STORYBOARD_VARIANT_META.execution_trace
  const VariantIcon = variantMeta.Icon

  const goPrev = () => {
    setStepIdx((prev) => Math.max(0, prev - 1))
  }

  const goNext = () => {
    setStepIdx((prev) => Math.min(steps.length - 1, prev + 1))
  }

  const checkpoint = currentStep.checkpoint
  const showCheckpoint =
    Boolean(checkpoint?.enabled) &&
    Array.isArray(checkpoint?.options) &&
    (checkpoint?.options.length ?? 0) >= 2
  const checkpointEntry = checkpointAnswers[currentStep.index]

  return (
    <section
      aria-label="Ejemplo paso a paso"
      className="overflow-hidden rounded-lg border border-slate-300 bg-white shadow-xs dark:border-slate-700 dark:bg-slate-900"
    >
      {/* 1 barra superior mínima */}
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-slate-50/90 px-3 py-2 dark:border-slate-800 dark:bg-slate-800/60">
        <div className="flex min-w-0 items-center gap-2">
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-800 dark:border-indigo-700/80 dark:bg-indigo-950/70 dark:text-indigo-200">
            <VariantIcon size={12} />
            Ejemplo paso a paso
          </span>
          <span className="inline-flex shrink-0 items-center gap-1 rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            <Code2 size={11} className="text-indigo-600 dark:text-indigo-400" />
            {(storyboard.language || 'code').toUpperCase()}
          </span>
          <h3 className="truncate text-xs font-semibold text-slate-900 dark:text-slate-100">
            {storyboard.title}
          </h3>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {storyboard.variant === 'error_contrast' && hasFixedCode && (
            <div className="inline-flex rounded border border-slate-300 bg-white p-0.5 text-[10px] font-semibold dark:border-slate-700 dark:bg-slate-900">
              <button
                type="button"
                onClick={() => setCodeViewTab('broken')}
                className={`rounded px-1.5 py-0.5 transition-colors ${
                  codeViewTab === 'broken'
                    ? 'bg-rose-600 text-white'
                    : 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100'
                }`}
              >
                Con fallo
              </button>
              <button
                type="button"
                onClick={() => setCodeViewTab('fixed')}
                className={`rounded px-1.5 py-0.5 transition-colors ${
                  codeViewTab === 'fixed'
                    ? 'bg-emerald-600 text-white'
                    : 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100'
                }`}
              >
                Corregido
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={onRegenerate}
            title="Regenerar ejemplo paso a paso"
            className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <RefreshCw size={12} />
            Regenerar
          </button>

          {onClose && (
            <button
              type="button"
              onClick={onClose}
              title="Colapsar ejemplo paso a paso"
              aria-label="Colapsar ejemplo paso a paso"
              className="inline-flex items-center justify-center rounded border border-slate-300 bg-white p-1 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <X size={13} />
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="flex items-center gap-1.5 border-b border-amber-200 bg-amber-50 px-3 py-1.5 text-[11px] text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <AlertTriangle size={12} className="shrink-0" />
          <span className="truncate">{error}</span>
        </div>
      )}

      {/* Layout vertical apilado: Código arriba (ancho completo), Estado abajo */}
      <div className="flex flex-col divide-y divide-slate-200 dark:divide-slate-800">
        {/* Bloque superior: Código numerado a ancho completo */}
        <div className="w-full bg-slate-50/50 dark:bg-slate-950/40">
          <div className="max-h-96 overflow-x-auto overflow-y-auto py-2 font-mono text-xs leading-relaxed">
            {codeLines.map((lineText, idx) => {
              const lineNo = idx + 1
              const isActive = activeLinesSet.has(lineNo)
              return (
                <div
                  key={lineNo}
                  className={`flex items-center px-3 py-0.5 transition-colors ${
                    isActive
                      ? 'border-l-2 border-indigo-500 bg-indigo-50/90 font-medium text-slate-950 opacity-100 dark:bg-indigo-950/50 dark:text-white'
                      : 'border-l-2 border-transparent text-slate-700 opacity-55 dark:text-slate-300'
                  }`}
                >
                  <span className="inline-flex w-4 shrink-0 items-center justify-center text-indigo-600 dark:text-indigo-400">
                    {isActive ? <ArrowRight size={11} /> : null}
                  </span>
                  <span className="w-7 shrink-0 select-none pr-2 text-right text-[11px] tabular-nums text-slate-400 dark:text-slate-500">
                    {lineNo}
                  </span>
                  <span className="whitespace-pre">{lineText || ' '}</span>
                </div>
              )
            })}
          </div>
        </div>

        {/* Bloque inferior: Explicación del paso + Estado/Traza + Checkpoint */}
        <div className="flex min-w-0 flex-col gap-3 p-3.5">
          {currentStep.caption && (
            <p className="rounded-md border border-indigo-200/80 bg-indigo-50/50 px-3 py-2 text-xs font-medium leading-relaxed text-slate-900 dark:border-indigo-800/70 dark:bg-indigo-950/30 dark:text-slate-100">
              {currentStep.caption}
            </p>
          )}

          <VariantSceneRenderer variant={storyboard.variant} state={currentStep.state} />

          {/* Micro-checkpoint interactivo de predicción */}
          {showCheckpoint && checkpoint && (
            <div className="rounded-md border border-amber-300 bg-amber-50/70 p-3 text-xs dark:border-amber-700/80 dark:bg-amber-950/25">
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 font-semibold text-amber-900 dark:text-amber-200">
                  <HelpCircle size={14} className="text-amber-600 dark:text-amber-400" />
                  Predicción activa
                </span>
                {!checkpointEntry && (
                  <button
                    type="button"
                    onClick={() =>
                      setCheckpointAnswers((prev) => ({
                        ...prev,
                        [currentStep.index]: { selectedIndex: null, skipped: true },
                      }))
                    }
                    className="rounded border border-amber-300 bg-white px-2 py-0.5 text-[11px] font-medium text-amber-900 hover:bg-amber-100 dark:border-amber-700 dark:bg-slate-900 dark:text-amber-200 dark:hover:bg-slate-800"
                  >
                    Saltar
                  </button>
                )}
              </div>

              <p className="mt-1.5 font-medium text-slate-900 dark:text-slate-100">
                {checkpoint.question}
              </p>

              <div className="mt-2 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {checkpoint.options.map((opt, optIdx) => {
                  const answered = Boolean(checkpointEntry)
                  const isSelected = checkpointEntry?.selectedIndex === optIdx
                  const isCorrect = optIdx === checkpoint.correct_index

                  let btnCls =
                    'border-slate-300 bg-white text-slate-800 hover:border-indigo-400 hover:bg-indigo-50/50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-indigo-500 dark:hover:bg-indigo-950/40'
                  if (answered) {
                    if (isCorrect) {
                      btnCls =
                        'border-emerald-500 bg-emerald-50 text-emerald-950 font-semibold dark:border-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-200'
                    } else if (isSelected && !isCorrect) {
                      btnCls =
                        'border-rose-500 bg-rose-50 text-rose-950 dark:border-rose-600 dark:bg-rose-950/50 dark:text-rose-200'
                    } else {
                      btnCls =
                        'border-slate-200 bg-white/60 text-slate-500 opacity-70 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-400'
                    }
                  }

                  return (
                    <button
                      key={optIdx}
                      type="button"
                      disabled={answered}
                      onClick={() =>
                        setCheckpointAnswers((prev) => ({
                          ...prev,
                          [currentStep.index]: { selectedIndex: optIdx, skipped: false },
                        }))
                      }
                      className={`flex items-center justify-between gap-2 rounded border px-2.5 py-1.5 text-left transition-colors ${btnCls}`}
                    >
                      <span className="break-words">{opt}</span>
                      {answered && isCorrect && (
                        <CheckCircle2
                          size={14}
                          className="shrink-0 text-emerald-600 dark:text-emerald-400"
                        />
                      )}
                      {answered && isSelected && !isCorrect && (
                        <XCircle
                          size={14}
                          className="shrink-0 text-rose-600 dark:text-rose-400"
                        />
                      )}
                    </button>
                  )
                })}
              </div>

              {checkpointEntry && (
                <div
                  className={`mt-2 flex items-start gap-2 rounded border px-2.5 py-2 ${
                    checkpointEntry.skipped
                      ? 'border-slate-300 bg-white text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300'
                      : checkpointEntry.selectedIndex === checkpoint.correct_index
                        ? 'border-emerald-300 bg-emerald-50/90 text-emerald-950 dark:border-emerald-700/80 dark:bg-emerald-950/40 dark:text-emerald-200'
                        : 'border-rose-300 bg-rose-50/90 text-rose-950 dark:border-rose-700/80 dark:bg-rose-950/40 dark:text-rose-200'
                  }`}
                >
                  {checkpointEntry.skipped ? (
                    <ArrowRight size={14} className="mt-0.5 shrink-0 text-slate-500" />
                  ) : checkpointEntry.selectedIndex === checkpoint.correct_index ? (
                    <CheckCircle2
                      size={14}
                      className="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400"
                    />
                  ) : (
                    <XCircle
                      size={14}
                      className="mt-0.5 shrink-0 text-rose-600 dark:text-rose-400"
                    />
                  )}
                  <div className="min-w-0 flex-1 break-words">
                    <span className="font-semibold">
                      {checkpointEntry.skipped
                        ? 'Respuesta explicada: '
                        : checkpointEntry.selectedIndex === checkpoint.correct_index
                          ? 'Correcto: '
                          : 'Revisa por qué: '}
                    </span>
                    <span>{checkpoint.explanation}</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 1 barra inferior fija de navegación manual */}
      <footer className="flex items-center justify-between gap-2 border-t border-slate-200 bg-slate-50/90 px-3 py-2 text-xs dark:border-slate-800 dark:bg-slate-800/60">
        <button
          type="button"
          onClick={goPrev}
          disabled={safeStepIdx === 0}
          className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-100 disabled:opacity-40 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <ChevronLeft size={14} />
          Anterior
        </button>

        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold tabular-nums text-slate-800 dark:text-slate-200">
            Paso {safeStepIdx + 1} / {steps.length}
          </span>
          {steps.length > 1 && steps.length <= 12 && (
            <div className="hidden items-center gap-1 sm:flex" aria-label="Selector de pasos">
              {steps.map((st, idx) => (
                <button
                  key={st.index}
                  type="button"
                  onClick={() => setStepIdx(idx)}
                  aria-label={`Ir al paso ${idx + 1}`}
                  className={`h-1.5 rounded-full transition-all ${
                    idx === safeStepIdx
                      ? 'w-4 bg-indigo-600 dark:bg-indigo-400'
                      : 'w-1.5 bg-slate-300 hover:bg-slate-400 dark:bg-slate-700 dark:hover:bg-slate-500'
                  }`}
                />
              ))}
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={goNext}
          disabled={safeStepIdx >= steps.length - 1}
          className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-3 py-1 text-xs font-semibold text-white transition-colors hover:bg-indigo-500 disabled:opacity-40 dark:bg-indigo-500 dark:hover:bg-indigo-400"
        >
          Siguiente
          <ArrowRight size={13} />
        </button>
      </footer>
    </section>
  )
}

// ============================================================================
// Renderizadores dedicados por variante (defensivos ante campos opcionales)
// ============================================================================

function VariantSceneRenderer({
  variant,
  state,
}: {
  variant: StoryboardVariant
  state: Record<string, unknown>
}) {
  const safeState = asRecord(state)
  switch (variant) {
    case 'execution_trace':
      return <ExecutionTraceView state={safeState} />
    case 'oop_dispatch':
      return <OopDispatchView state={safeState} />
    case 'error_contrast':
      return <ErrorContrastView state={safeState} />
    case 'data_structure':
      return <DataStructureView state={safeState} />
    case 'sql_pipeline':
      return <SqlPipelineView state={safeState} />
    default:
      return <ExecutionTraceView state={safeState} />
  }
}

// 1. execution_trace
function ExecutionTraceView({ state }: { state: Record<string, unknown> }) {
  const frames = asArray(state.frames)
  const heap = asArray(state.heap)
  const delta = asStr(state.delta).trim()
  const rawStdout = state.stdout
  const stdoutLines = Array.isArray(rawStdout)
    ? rawStdout.map((x) => asStr(x)).filter(Boolean)
    : asStr(rawStdout).trim()
      ? asStr(rawStdout).split('\n')
      : []

  return (
    <div className="flex flex-col gap-2.5 text-xs">
      {delta && (
        <div className="inline-flex items-center gap-1.5 self-start rounded-full border border-emerald-300 bg-emerald-50 px-2.5 py-0.5 text-[11px] font-medium text-emerald-900 dark:border-emerald-700/80 dark:bg-emerald-950/40 dark:text-emerald-200">
          <ArrowRight size={11} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
          <span>{delta}</span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {/* Stack Frames */}
        <div className="flex flex-col gap-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Stack (Pila de llamadas)
          </div>
          {frames.length === 0 ? (
            <div className="rounded border border-dashed border-slate-300 p-2.5 text-[11px] text-slate-500 dark:border-slate-700 dark:text-slate-400">
              Sin frames activos en este instante.
            </div>
          ) : (
            frames.map((rawFrame, fIdx) => {
              const f = asRecord(rawFrame)
              const frameName = asStr(f.name ?? f.frame ?? f.method, `frame_${fIdx}`)
              const isActive = f.active !== undefined ? asBool(f.active) : fIdx === 0
              const vars = asArray(f.variables ?? f.vars ?? f.locals)

              return (
                <div
                  key={`${frameName}-${fIdx}`}
                  className={`overflow-hidden rounded-md border ${
                    isActive
                      ? 'border-indigo-300 bg-white dark:border-indigo-700 dark:bg-slate-900'
                      : 'border-slate-200 bg-slate-50/70 opacity-85 dark:border-slate-800 dark:bg-slate-900/50'
                  }`}
                >
                  <div className="flex items-center justify-between border-b border-slate-200 bg-slate-100/80 px-2.5 py-1 dark:border-slate-800 dark:bg-slate-800/70">
                    <span className="font-mono text-[11px] font-semibold text-slate-900 dark:text-slate-100">
                      {frameName}
                    </span>
                    {isActive && (
                      <span className="rounded bg-indigo-600 px-1.5 py-0.5 text-[10px] font-semibold text-white dark:bg-indigo-500">
                        Activo
                      </span>
                    )}
                  </div>

                  {vars.length === 0 ? (
                    <div className="px-2.5 py-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                      (sin variables locales)
                    </div>
                  ) : (
                    <table className="w-full text-left font-mono text-[11px]">
                      <tbody>
                        {vars.map((rawVar, vIdx) => {
                          const v = asRecord(rawVar)
                          const vName = asStr(v.name, `v${vIdx}`)
                          const vType = asStr(v.type)
                          const vVal = asStr(v.value, 'null')
                          const refId = asStr(v.ref_id ?? v.address ?? v.ref)
                          const changed = asBool(v.changed)

                          return (
                            <tr
                              key={`${vName}-${vIdx}`}
                              className={`border-b border-slate-100 last:border-b-0 dark:border-slate-800/70 ${
                                changed
                                  ? 'bg-emerald-50/90 font-semibold text-emerald-950 dark:bg-emerald-950/40 dark:text-emerald-200'
                                  : 'text-slate-800 dark:text-slate-200'
                              }`}
                            >
                              <td className="px-2 py-1">{vName}</td>
                              {vType && (
                                <td className="px-1 py-1 text-[10px] text-slate-500 dark:text-slate-400">
                                  {vType}
                                </td>
                              )}
                              <td className="px-2 py-1 text-right">
                                {refId ? (
                                  <span className="inline-flex items-center gap-1 rounded bg-amber-100/80 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900 dark:bg-amber-900/40 dark:text-amber-200">
                                    -&gt; {formatAddr(refId)}
                                  </span>
                                ) : (
                                  vVal
                                )}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              )
            })
          )}
        </div>

        {/* Heap Cards */}
        <div className="flex flex-col gap-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Heap (Objetos en memoria)
          </div>
          {heap.length === 0 ? (
            <div className="rounded border border-dashed border-slate-300 p-2.5 text-[11px] text-slate-500 dark:border-slate-700 dark:text-slate-400">
              Sin objetos en el Heap.
            </div>
          ) : (
            heap.map((rawObj, hIdx) => {
              const obj = asRecord(rawObj)
              const className = asStr(obj.class_name ?? obj.type ?? obj.class, 'Object')
              const addr = formatAddr(asStr(obj.address ?? obj.id ?? obj.ref_id, `obj${hIdx + 1}`))
              const rawFields = obj.fields ?? obj.properties
              const fieldsList = Array.isArray(rawFields)
                ? rawFields.map((item) => asRecord(item))
                : Object.entries(asRecord(rawFields)).map(([k, v]) => ({
                    name: k,
                    value: v,
                    changed: false,
                  }))

              return (
                <div
                  key={`${addr}-${hIdx}`}
                  className="overflow-hidden rounded-md border border-amber-300/80 bg-amber-50/40 dark:border-amber-700/70 dark:bg-amber-950/20"
                >
                  <div className="flex items-center justify-between border-b border-amber-200/80 bg-amber-100/60 px-2.5 py-1 font-mono text-[11px] dark:border-amber-800/60 dark:bg-amber-950/50">
                    <span className="font-semibold text-amber-950 dark:text-amber-200">
                      {className}
                    </span>
                    <span className="rounded bg-white/80 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900 dark:bg-slate-900 dark:text-amber-300">
                      {addr}
                    </span>
                  </div>
                  {fieldsList.length === 0 ? (
                    <div className="px-2.5 py-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                      (sin atributos)
                    </div>
                  ) : (
                    <div className="divide-y divide-amber-200/50 font-mono text-[11px] dark:divide-amber-900/40">
                      {fieldsList.map((fld, flIdx) => {
                        const changed = asBool(fld.changed)
                        return (
                          <div
                            key={flIdx}
                            className={`flex items-center justify-between px-2.5 py-1 ${
                              changed
                                ? 'bg-emerald-100/80 font-semibold text-emerald-950 dark:bg-emerald-950/50 dark:text-emerald-200'
                                : 'text-slate-800 dark:text-slate-200'
                            }`}
                          >
                            <span>{asStr(fld.name)}</span>
                            <span>{asStr(fld.value, 'null')}</span>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Consola stdout */}
      {stdoutLines.length > 0 && (
        <div className="overflow-hidden rounded-md border border-slate-700 bg-slate-900 text-slate-100 dark:border-slate-700 dark:bg-slate-950">
          <div className="flex items-center gap-1.5 border-b border-slate-800 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            <Terminal size={11} /> stdout
          </div>
          <pre className="overflow-x-auto px-2.5 py-1.5 font-mono text-[11px] text-emerald-300">
            {stdoutLines.join('\n')}
          </pre>
        </div>
      )}
    </div>
  )
}

// 2. oop_dispatch
function OopDispatchView({ state }: { state: Record<string, unknown> }) {
  const classes = asArray(state.classes).map((c) => asRecord(c))
  const references = asArray(state.references).map((r) => asRecord(r))
  const heapObjects = asArray(state.heap_objects).map((h) => asRecord(h))
  const dispatch = asRecord(state.dispatch)

  const callExpr = asStr(dispatch.call_expr)
  const staticCheck = asStr(dispatch.static_check)
  const lookupPath = asArray(dispatch.lookup_path).map((p) => asStr(p)).filter(Boolean)
  const resolvedMethod = asStr(dispatch.resolved_method)
  const resolvedClass = asStr(dispatch.resolved_class)
  const viaSuper = asBool(dispatch.via_super)

  return (
    <div className="flex flex-col gap-2.5 text-xs">
      {/* Mini-arbol jerarquico de clases */}
      {classes.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Jerarquía de clases
          </div>
          <div className="flex flex-wrap items-stretch gap-2">
            {classes.map((cls, idx) => {
              const name = asStr(cls.name, `Clase${idx + 1}`)
              const parent = asStr(cls.extends ?? cls.superclass ?? cls.parent)
              const active = asBool(cls.active ?? cls.is_active)
              const methods = asArray(cls.methods)

              return (
                <div
                  key={`${name}-${idx}`}
                  className={`flex min-w-[9.5rem] flex-1 flex-col rounded-md border p-2 ${
                    active
                      ? 'border-indigo-500 bg-indigo-50/70 dark:border-indigo-400 dark:bg-indigo-950/40'
                      : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/60'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-1 border-b border-slate-200 pb-1 dark:border-slate-800">
                    <span className="font-mono text-[11px] font-bold text-slate-900 dark:text-slate-100">
                      {name}
                    </span>
                    {parent && (
                      <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                        <svg
                          width="12"
                          height="10"
                          viewBox="0 0 12 10"
                          fill="none"
                          aria-hidden="true"
                          className="shrink-0 text-indigo-500"
                        >
                          <path
                            d="M1 5H10M10 5L6.5 1.5M10 5L6.5 8.5"
                            stroke="currentColor"
                            strokeWidth="1.5"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          />
                        </svg>
                        extends {parent}
                      </span>
                    )}
                  </div>
                  {methods.length > 0 && (
                    <ul className="mt-1.5 flex flex-col gap-0.5 font-mono text-[11px] text-slate-700 dark:text-slate-300">
                      {methods.map((m, mIdx) => {
                        const mRec = typeof m === 'object' && m !== null ? asRecord(m) : null
                        const mLabel = mRec ? asStr(mRec.signature ?? mRec.name) : asStr(m)
                        const mActive = mRec ? asBool(mRec.active ?? mRec.overridden) : false
                        return (
                          <li
                            key={mIdx}
                            className={`rounded px-1 py-0.5 ${
                              mActive
                                ? 'bg-emerald-100/80 font-semibold text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200'
                                : ''
                            }`}
                          >
                            {mLabel}
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Comparativa Tipo estatico vs Tipo dinamico (Heap) */}
      {(references.length > 0 || heapObjects.length > 0) && (
        <div className="grid grid-cols-1 gap-2 rounded-md border border-slate-200 bg-slate-50/70 p-2.5 sm:grid-cols-2 dark:border-slate-800 dark:bg-slate-900/50">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Tipo estático (Referencia)
            </div>
            <div className="mt-1 flex flex-col gap-1">
              {references.map((ref, idx) => {
                const rName = asStr(ref.var_name ?? ref.name, `ref${idx}`)
                const sType = asStr(ref.static_type ?? ref.declared_type ?? ref.type, '?')
                const dynType = asStr(ref.dynamic_type)
                const target = asStr(ref.heap_id ?? ref.ref_id ?? ref.address ?? ref.target_id)
                return (
                  <div
                    key={idx}
                    className="flex items-center justify-between gap-2 rounded border border-slate-200 bg-white px-2 py-1 font-mono text-[11px] dark:border-slate-700 dark:bg-slate-900"
                  >
                    <span>
                      <span className="text-indigo-600 dark:text-indigo-400">{sType}</span> {rName}
                    </span>
                    {(target || dynType) && (
                      <span className="text-[10px] font-semibold text-amber-700 dark:text-amber-300">
                        -&gt; {dynType ? `${dynType} ` : ''}
                        {target ? formatAddr(target) : ''}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Tipo dinámico (Objeto en Heap)
            </div>
            <div className="mt-1 flex flex-col gap-1">
              {heapObjects.map((hObj, idx) => {
                const addr = formatAddr(asStr(hObj.address ?? hObj.id ?? hObj.ref_id, `obj${idx + 1}`))
                const dType = asStr(hObj.dynamic_type ?? hObj.class_name ?? hObj.type, 'Object')
                return (
                  <div
                    key={idx}
                    className="flex items-center justify-between rounded border border-amber-300/80 bg-amber-50/60 px-2 py-1 font-mono text-[11px] dark:border-amber-700/70 dark:bg-amber-950/30"
                  >
                    <span className="font-semibold text-amber-950 dark:text-amber-200">
                      new {dType}()
                    </span>
                    <span className="text-[10px] font-semibold text-amber-800 dark:text-amber-300">
                      {addr}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* Ruta de lookup (@Override / super()) */}
      {(callExpr || lookupPath.length > 0 || resolvedMethod) && (
        <div className="rounded-md border border-indigo-200 bg-indigo-50/50 p-2.5 dark:border-indigo-800/70 dark:bg-indigo-950/25">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] font-semibold text-indigo-950 dark:text-indigo-200">
              Ruta de resolución dinámica (@Override / super)
            </span>
            {callExpr && (
              <code className="rounded bg-white px-2 py-0.5 font-mono text-[11px] font-semibold text-indigo-700 dark:bg-slate-900 dark:text-indigo-300">
                {callExpr}
              </code>
            )}
          </div>

          {staticCheck && (
            <p className="mt-1 text-[11px] text-slate-700 dark:text-slate-300">
              <span className="font-semibold">Chequeo estático:</span> {staticCheck}
            </p>
          )}

          {lookupPath.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 font-mono text-[11px]">
              {lookupPath.map((stepName, idx) => (
                <span key={idx} className="inline-flex items-center gap-1.5">
                  <span className="rounded border border-indigo-300 bg-white px-2 py-0.5 font-medium text-slate-900 dark:border-indigo-700 dark:bg-slate-900 dark:text-slate-100">
                    {stepName}
                  </span>
                  {idx < lookupPath.length - 1 && (
                    <ArrowRight size={12} className="text-indigo-500" />
                  )}
                </span>
              ))}
            </div>
          )}

          {resolvedMethod && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="inline-flex items-center gap-1.5 rounded border border-emerald-300 bg-emerald-50 px-2 py-1 font-mono text-[11px] font-semibold text-emerald-900 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200">
                <CheckCircle2 size={12} className="text-emerald-600 dark:text-emerald-400" />
                Método ejecutado: {resolvedMethod}
                {resolvedClass && !resolvedMethod.includes(resolvedClass) ? ` (${resolvedClass})` : ''}
              </span>
              {viaSuper && (
                <span className="rounded border border-violet-300 bg-violet-50 px-2 py-1 font-mono text-[10px] font-semibold text-violet-900 dark:border-violet-700 dark:bg-violet-950/40 dark:text-violet-200">
                  vía super()
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// 3. error_contrast
function ErrorContrastView({ state }: { state: Record<string, unknown> }) {
  const rawPhase = asStr(state.phase).toLowerCase().trim()
  const codeView = asStr(state.code_view).toLowerCase().trim()
  const exception = state.exception ? asRecord(state.exception) : null
  const callStack = asArray(state.call_stack).map((f) => asRecord(f))
  const contrast = state.contrast ? asRecord(state.contrast) : null

  const isFixedDiffPhase = rawPhase === 'fixed_diff' || rawPhase === 'contrast_fix'

  let activePhase = 1
  if (
    rawPhase.includes('unwind') ||
    rawPhase.includes('propag') ||
    rawPhase === '2'
  ) {
    activePhase = 2
  } else if (
    isFixedDiffPhase ||
    rawPhase.includes('contrast') ||
    rawPhase.includes('fix') ||
    rawPhase.includes('after') ||
    rawPhase === '3' ||
    codeView === 'fixed'
  ) {
    activePhase = 3
  }

  const exType = exception ? asStr(exception.type) : ''
  const exMessage = exception ? asStr(exception.message) : ''
  const exLine = exception ? asNum(exception.line) : null

  const bugCause = contrast ? asStr(contrast.bug_cause).trim() : ''
  const beforeCode = contrast ? asStr(contrast.before ?? contrast.broken_line).trim() : ''
  const afterCode = contrast ? asStr(contrast.after ?? contrast.fixed_line).trim() : ''
  const fixExplanation = contrast ? asStr(contrast.fix_explanation).trim() : ''
  const showContrast = isFixedDiffPhase && Boolean(beforeCode || afterCode)

  return (
    <div className="flex flex-col gap-2.5 text-xs">
      {/* Indicador visual de las 3 fases */}
      <div className="flex flex-wrap items-center gap-1.5">
        {[
          { n: 1, label: '1. Ejecución con fallo' },
          { n: 2, label: '2. Stack unwinding' },
          { n: 3, label: '3. Antes / Después' },
        ].map((ph, idx) => (
          <span key={ph.n} className="inline-flex items-center gap-1.5">
            <span
              className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${
                activePhase === ph.n
                  ? ph.n === 1
                    ? 'bg-rose-600 text-white'
                    : ph.n === 2
                      ? 'bg-amber-500 text-slate-950'
                      : 'bg-emerald-600 text-white'
                  : 'border border-slate-200 bg-slate-100 text-slate-500 dark:border-slate-800 dark:bg-slate-800/70 dark:text-slate-400'
              }`}
            >
              {ph.label}
            </span>
            {idx < 2 && <ArrowRight size={11} className="text-slate-400" />}
          </span>
        ))}
      </div>

      {/* Alerta de excepcion */}
      {(exType || exMessage) && (
        <div className="rounded-md border border-rose-300 bg-rose-50/90 p-2.5 text-rose-950 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 font-mono text-xs font-bold">
              <AlertTriangle size={14} className="shrink-0 text-rose-600 dark:text-rose-400" />
              {exType || 'Exception'}
            </span>
            {exLine !== null && (
              <span className="rounded bg-rose-200/80 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-rose-900 dark:bg-rose-900/70 dark:text-rose-200">
                Línea {exLine}
              </span>
            )}
          </div>
          {exMessage && <p className="mt-1 break-words text-[11px]">{exMessage}</p>}
        </div>
      )}

      {/* Pila call_stack coloreada por status */}
      {callStack.length > 0 && (
        <div className="flex flex-col gap-1">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Call Stack
          </div>
          {callStack.map((frame, idx) => {
            const fName = asStr(frame.frame ?? frame.name ?? frame.method, `frame_${idx}`)
            const fLine = asNum(frame.line)
            const status = asStr(frame.status, 'active').toLowerCase()

            let styleCls =
              'border-indigo-300 bg-indigo-50 text-indigo-950 dark:border-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-200'
            if (status === 'crashed') {
              styleCls =
                'border-rose-400 bg-rose-50 text-rose-950 dark:border-rose-700 dark:bg-rose-950/40 dark:text-rose-200'
            } else if (status === 'unwinding') {
              styleCls =
                'border-amber-400 bg-amber-50 text-amber-950 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200'
            } else if (status === 'catching') {
              styleCls =
                'border-emerald-400 bg-emerald-50 text-emerald-950 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200'
            }

            return (
              <div
                key={idx}
                className={`flex items-center justify-between rounded border px-2.5 py-1 font-mono text-[11px] ${styleCls}`}
              >
                <span className="font-semibold">{fName}</span>
                <div className="flex items-center gap-2 text-[10px]">
                  {fLine !== null && <span>Línea {fLine}</span>}
                  <span className="rounded bg-black/5 px-1.5 py-0.5 uppercase dark:bg-white/10">
                    {status}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Vista de contraste Antes -> Despues (SOLO en fase fixed_diff y con contenido) */}
      {showContrast && (
        <div className="flex flex-col gap-2 rounded-md border border-slate-200 bg-slate-50/80 p-2.5 dark:border-slate-800 dark:bg-slate-900/60">
          {bugCause && (
            <p className="text-[11px] font-medium text-slate-800 dark:text-slate-200">
              <span className="font-semibold text-rose-700 dark:text-rose-400">Causa raíz: </span>
              {bugCause}
            </p>
          )}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {beforeCode && (
              <div className="rounded border border-rose-300 bg-rose-50/90 p-2 dark:border-rose-800 dark:bg-rose-950/35">
                <div className="text-[10px] font-semibold uppercase text-rose-800 dark:text-rose-300">
                  Antes (con fallo)
                </div>
                <pre className="mt-1 overflow-x-auto font-mono text-[11px] text-rose-950 dark:text-rose-200">
                  {beforeCode}
                </pre>
              </div>
            )}
            {afterCode && (
              <div className="rounded border border-emerald-300 bg-emerald-50/90 p-2 dark:border-emerald-800 dark:bg-emerald-950/35">
                <div className="text-[10px] font-semibold uppercase text-emerald-800 dark:text-emerald-300">
                  Después (corregido)
                </div>
                <pre className="mt-1 overflow-x-auto font-mono text-[11px] text-emerald-950 dark:text-emerald-200">
                  {afterCode}
                </pre>
              </div>
            )}
          </div>
          {fixExplanation && (
            <p className="text-[11px] text-slate-700 dark:text-slate-300">{fixExplanation}</p>
          )}
        </div>
      )}
    </div>
  )
}

// 4. data_structure
function DataStructureView({ state }: { state: Record<string, unknown> }) {
  const structureType = asStr(state.structure_type, 'array').toLowerCase()
  const label = asStr(state.label, structureType.toUpperCase())
  const size = asNum(state.size)
  const capacity = asNum(state.capacity)
  const operation = asStr(state.operation)
  const hashFormula = asStr(state.hash_formula)
  const cells = asArray(state.cells).map((c) => asRecord(c))
  const pointers = asArray(state.pointers).map((p) => asRecord(p))
  const buckets = asArray(state.buckets).map((b) => asRecord(b))

  const isLinked =
    structureType.includes('list') ||
    structureType.includes('linked') ||
    cells.some((c) => c.next_index !== undefined)

  const pointersByIndex = new Map<number, string[]>()
  const detachedPointers: { name: string; target: string }[] = []

  pointers.forEach((p, idx) => {
    const pName = asStr(p.name ?? p.label, `p${idx}`)
    const pIdx = asNum(p.index ?? p.target_index)
    if (pIdx !== null && cells.some((c, cI) => (asNum(c.index) ?? cI) === pIdx)) {
      const prev = pointersByIndex.get(pIdx) ?? []
      prev.push(pName)
      pointersByIndex.set(pIdx, prev)
    } else {
      detachedPointers.push({ name: pName, target: pIdx !== null ? String(pIdx) : 'null' })
    }
  })

  return (
    <div className="flex flex-col gap-2.5 text-xs">
      {/* Header con label, size / capacity y operation */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 bg-slate-50/80 px-2.5 py-1.5 dark:border-slate-800 dark:bg-slate-800/50">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-bold text-slate-900 dark:text-slate-100">
            {label}
          </span>
          {(size !== null || capacity !== null) && (
            <span className="rounded bg-white px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {size !== null ? `size=${size}` : ''}
              {size !== null && capacity !== null ? ' / ' : ''}
              {capacity !== null ? `cap=${capacity}` : ''}
            </span>
          )}
        </div>
        {operation && (
          <span className="rounded bg-indigo-100 px-2 py-0.5 font-mono text-[11px] font-semibold text-indigo-900 dark:bg-indigo-950/70 dark:text-indigo-200">
            {operation}
          </span>
        )}
      </div>

      {/* Celdas contiguas + punteros flotantes */}
      {cells.length > 0 && (
        <div className="overflow-x-auto py-1">
          <div className="inline-flex items-end gap-1.5">
            {cells.map((cell, idx) => {
              const cIndex = asNum(cell.index) ?? idx
              const cVal = asStr(cell.value, '')
              const cState = asStr(cell.state, 'normal').toLowerCase()
              const nextIdx =
                cell.next_index === null
                  ? 'null'
                  : cell.next_index !== undefined
                    ? asStr(cell.next_index)
                    : null
              const cellPtrs = pointersByIndex.get(cIndex) ?? []

              let boxCls =
                'border-slate-300 bg-white text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100'
              if (cState === 'active') {
                boxCls =
                  'border-indigo-500 bg-indigo-50 font-bold text-indigo-950 ring-1 ring-indigo-400 dark:border-indigo-400 dark:bg-indigo-950/60 dark:text-indigo-100'
              } else if (cState === 'changed') {
                boxCls =
                  'border-emerald-500 bg-emerald-50 font-bold text-emerald-950 ring-1 ring-emerald-400 dark:border-emerald-400 dark:bg-emerald-950/60 dark:text-emerald-100'
              } else if (cState === 'empty') {
                boxCls =
                  'border-dashed border-slate-300 bg-slate-50/50 text-slate-400 opacity-60 dark:border-slate-700 dark:bg-slate-900/30 dark:text-slate-500'
              }

              return (
                <div key={`${cIndex}-${idx}`} className="flex items-end gap-1">
                  <div className="flex flex-col items-center">
                    {/* Punteros flotantes arriba de la celda */}
                    <div className="mb-1 flex min-h-[1.6rem] flex-col items-center justify-end">
                      {cellPtrs.length > 0 && (
                        <>
                          <div className="flex flex-wrap justify-center gap-0.5">
                            {cellPtrs.map((pName) => (
                              <span
                                key={pName}
                                className="rounded bg-indigo-600 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-white dark:bg-indigo-500"
                              >
                                {pName}
                              </span>
                            ))}
                          </div>
                          <ArrowDown
                            size={11}
                            className="mt-0.5 text-indigo-600 dark:text-indigo-400"
                          />
                        </>
                      )}
                    </div>

                    {/* Celda */}
                    <div
                      className={`flex min-w-[3.1rem] flex-col items-center rounded border px-2.5 py-1.5 font-mono transition-colors ${boxCls}`}
                    >
                      <span className="text-xs">{cVal !== '' ? cVal : '_'}</span>
                      {isLinked && nextIdx !== null && (
                        <span className="mt-0.5 border-t border-slate-200 pt-0.5 text-[9px] text-slate-500 dark:border-slate-700 dark:text-slate-400">
                          next:{nextIdx}
                        </span>
                      )}
                    </div>

                    {/* Indice inferior */}
                    <span className="mt-1 font-mono text-[10px] tabular-nums text-slate-500 dark:text-slate-400">
                      [{cIndex}]
                    </span>
                  </div>

                  {isLinked && idx < cells.length - 1 && (
                    <ArrowRight
                      size={13}
                      className="mb-5 shrink-0 text-slate-400 dark:text-slate-500"
                    />
                  )}
                </div>
              )
            })}
          </div>

          {detachedPointers.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {detachedPointers.map((dp, i) => (
                <span
                  key={i}
                  className="rounded border border-slate-300 bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300"
                >
                  {dp.name} -&gt; {dp.target}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Buckets para HashMap */}
      {(buckets.length > 0 || structureType === 'hashmap') && (
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Buckets Hash
            </span>
            <code className="rounded border border-indigo-200 bg-indigo-50 px-2 py-0.5 font-mono text-[10px] font-semibold text-indigo-800 dark:border-indigo-800 dark:bg-indigo-950/50 dark:text-indigo-200">
              {hashFormula || `hash(k) % ${Math.max(1, buckets.length)}`}
            </code>
          </div>

          <div className="flex flex-col gap-1">
            {buckets.map((b, bIdx) => {
              const bucketIdx = asNum(b.index ?? b.bucket) ?? bIdx
              const entries = asArray(b.entries ?? b.items ?? b.chain).map((e) => asRecord(e))
              // El backend coloca hash_formula/active en cada entrada; se admite tambien a nivel bucket.
              const activeEntry = entries.find((e) => asBool(e.active))
              const bFormula = asStr(
                b.hash_formula ?? activeEntry?.hash_formula ?? entries[0]?.hash_formula,
              )
              const activeBucket = asBool(b.active) || Boolean(activeEntry)

              return (
                <div
                  key={bucketIdx}
                  className={`flex flex-wrap items-center gap-2 rounded border px-2.5 py-1.5 font-mono text-[11px] ${
                    activeBucket
                      ? 'border-indigo-400 bg-indigo-50/70 dark:border-indigo-600 dark:bg-indigo-950/35'
                      : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/60'
                  }`}
                >
                  <span className="w-10 shrink-0 font-semibold tabular-nums text-slate-600 dark:text-slate-400">
                    [{bucketIdx}]
                  </span>

                  {entries.length === 0 ? (
                    <span className="text-[11px] text-slate-400 dark:text-slate-500">vacío</span>
                  ) : (
                    <div className="flex flex-wrap items-center gap-1.5">
                      {entries.map((ent, eIdx) => {
                        const k = asStr(ent.key ?? ent.k)
                        const v = asStr(ent.value ?? ent.v)
                        const changed = asBool(ent.changed ?? ent.active)
                        return (
                          <span key={eIdx} className="inline-flex items-center gap-1.5">
                            <span
                              className={`rounded border px-2 py-0.5 ${
                                changed
                                  ? 'border-emerald-400 bg-emerald-50 font-semibold text-emerald-950 dark:border-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-200'
                                  : 'border-slate-300 bg-slate-50 text-slate-800 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200'
                              }`}
                            >
                              {k} -&gt; {v}
                            </span>
                            {eIdx < entries.length - 1 && (
                              <ArrowRight size={11} className="text-amber-500" />
                            )}
                          </span>
                        )
                      })}
                    </div>
                  )}

                  {bFormula && (
                    <span className="ml-auto text-[10px] text-indigo-700 dark:text-indigo-300">
                      {bFormula}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// 5. sql_pipeline
const DEFAULT_SQL_STAGES = ['FROM/JOIN', 'WHERE', 'GROUP BY', 'HAVING', 'SELECT', 'ORDER BY']

const GROUP_PALETTE = [
  'border-l-indigo-500 bg-indigo-50/40 dark:bg-indigo-950/25',
  'border-l-emerald-500 bg-emerald-50/40 dark:bg-emerald-950/25',
  'border-l-amber-500 bg-amber-50/40 dark:bg-amber-950/25',
  'border-l-sky-500 bg-sky-50/40 dark:bg-sky-950/25',
  'border-l-violet-500 bg-violet-50/40 dark:bg-violet-950/25',
]

function SqlPipelineView({ state }: { state: Record<string, unknown> }) {
  const activeClause = asStr(state.active_clause).toUpperCase().trim()
  const rawStages = asArray(state.pipeline_stages).map((s) => asStr(s).trim()).filter(Boolean)
  const stages = rawStages.length > 0 ? rawStages : DEFAULT_SQL_STAGES
  const clauseSql = asStr(state.clause_sql)
  const columns = asArray(state.columns).map((c) => asStr(c))
  const rows = asArray(state.rows)
  const note = asStr(state.note)

  const groupKeys = Array.from(
    new Set(
      rows
        .map((r) => asStr(asRecord(r).group_key).trim())
        .filter((g) => g.length > 0),
    ),
  )

  const matchesClause = (stageLabel: string): boolean => {
    if (!activeClause) return false
    const normStage = stageLabel.toUpperCase()
    if (normStage === activeClause) return true
    if (normStage === 'FROM/JOIN' && (activeClause === 'FROM' || activeClause === 'JOIN')) {
      return true
    }
    return normStage.includes(activeClause) || activeClause.includes(normStage)
  }

  return (
    <div className="flex flex-col gap-2.5 text-xs">
      {/* Barra de etapas en orden logico real */}
      <div className="flex flex-wrap items-center gap-1">
        {stages.map((st, idx) => {
          const isCurrent = matchesClause(st)
          return (
            <span key={`${st}-${idx}`} className="inline-flex items-center gap-1">
              <span
                className={`rounded px-2 py-0.5 font-mono text-[10px] font-semibold ${
                  isCurrent
                    ? 'bg-indigo-600 text-white dark:bg-indigo-500'
                    : 'border border-slate-200 bg-slate-100 text-slate-600 dark:border-slate-800 dark:bg-slate-800/80 dark:text-slate-400'
                }`}
              >
                {st}
              </span>
              {idx < stages.length - 1 && <ArrowRight size={10} className="text-slate-400" />}
            </span>
          )
        })}
      </div>

      {clauseSql && (
        <div className="rounded border border-indigo-200 bg-indigo-50/60 px-2.5 py-1.5 font-mono text-[11px] font-medium text-indigo-950 dark:border-indigo-800/70 dark:bg-indigo-950/35 dark:text-indigo-200">
          {clauseSql}
        </div>
      )}

      {/* Mini-tabla de filas intermedias */}
      {columns.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-slate-200 dark:border-slate-800">
          <table className="w-full border-collapse text-left font-mono text-[11px]">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-100/90 text-slate-700 dark:border-slate-800 dark:bg-slate-800/80 dark:text-slate-300">
                {groupKeys.length > 0 && (
                  <th className="px-2 py-1 text-[10px] font-semibold uppercase">Grupo</th>
                )}
                {columns.map((col, idx) => (
                  <th key={idx} className="px-2.5 py-1 font-semibold">
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/70">
              {rows.map((rawRow, rIdx) => {
                const rowRec = asRecord(rawRow)
                const status = asStr(rowRec.status, 'kept').toLowerCase()
                const groupKey = asStr(rowRec.group_key).trim()
                const rawVals = rowRec.values ?? rowRec.cells ?? rowRec.data
                const cellValues = Array.isArray(rawVals)
                  ? rawVals.map((v) => asStr(v, 'NULL'))
                  : Array.isArray(rawRow)
                    ? rawRow.map((v) => asStr(v, 'NULL'))
                    : columns.map((col) => asStr(rowRec[col], 'NULL'))

                const isFilteredOut = status === 'filtered_out'
                const groupIdx = groupKey ? groupKeys.indexOf(groupKey) : -1
                const groupCls =
                  !isFilteredOut && groupIdx >= 0
                    ? `border-l-2 ${GROUP_PALETTE[groupIdx % GROUP_PALETTE.length]}`
                    : ''

                return (
                  <tr
                    key={rIdx}
                    className={`${
                      isFilteredOut
                        ? 'bg-rose-50/50 text-slate-500 line-through opacity-45 dark:bg-rose-950/20 dark:text-slate-400'
                        : status === 'projected'
                          ? 'bg-emerald-50/35 text-slate-900 dark:bg-emerald-950/15 dark:text-slate-100'
                          : 'bg-white text-slate-900 dark:bg-slate-900 dark:text-slate-100'
                    } ${groupCls}`}
                  >
                    {groupKeys.length > 0 && (
                      <td className="px-2 py-1">
                        {groupKey ? (
                          <span className="rounded bg-slate-200/80 px-1.5 py-0.5 text-[10px] font-semibold text-slate-800 dark:bg-slate-800 dark:text-slate-200">
                            {groupKey}
                          </span>
                        ) : (
                          '-'
                        )}
                      </td>
                    )}
                    {columns.map((_, cIdx) => (
                      <td key={cIdx} className="px-2.5 py-1">
                        {cellValues[cIdx] ?? 'NULL'}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {note && (
        <p className="text-[11px] text-slate-600 dark:text-slate-300">{note}</p>
      )}
    </div>
  )
}
