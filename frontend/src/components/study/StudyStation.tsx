import { useCallback, useState } from 'react'
import { BookOpen, ClipboardCheck, Clock, Dumbbell, Trophy } from 'lucide-react'
import { inCooldown, type EvaluateResponse, type NodeProgress, type PackNode } from '../../api/study'
import ConfirmDialog from './ConfirmDialog'
import EvalTab from './EvalTab'
import StoryTab from './StoryTab'
import { formatRemaining, LEVEL_STYLE } from './studyUtils'

interface Props {
  courseId: string
  node: PackNode
  progress: NodeProgress
  worldMetaphor: string | null
  now: number
  onSubmit: (req: {
    answers: { prompt_id: string; text: string }[]
    covered_points?: string[]
  }) => Promise<EvaluateResponse>
  onRegenerateStory: () => Promise<void>
  onInProgressChange: (v: boolean) => void
}

type Tab = 'story' | 'eval'

/** Se monta con `key={node.id}`: al cambiar de nodo el estado local se reinicia. */
export default function StudyStation({
  courseId,
  node,
  progress,
  worldMetaphor,
  now,
  onSubmit,
  onRegenerateStory,
  onInProgressChange,
}: Props) {
  const [tab, setTab] = useState<Tab>('story')
  const [inProgress, setInProgress] = useState(false)
  const [askLeave, setAskLeave] = useState(false)
  const lvl = LEVEL_STYLE[progress.mastery_level] ?? LEVEL_STYLE[0]
  const cooling = inCooldown(progress, now)
  const remaining = cooling ? new Date(progress.next_review_at!).getTime() - now : 0

  const handleProgress = useCallback(
    (v: boolean) => {
      setInProgress(v)
      onInProgressChange(v)
    },
    [onInProgressChange],
  )

  const goStory = () => (inProgress ? setAskLeave(true) : setTab('story'))

  const tabCls = (active: boolean) =>
    `inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${
      active
        ? 'border-slate-900 dark:border-slate-100'
        : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-slate-100'
    }`

  return (
    <section className="flex h-full min-h-0 flex-col">
      <header className="border-b border-slate-200 px-5 pt-4 dark:border-slate-800">
        <div className="flex items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
          <span className="truncate">{node.block}</span>
          <span className="shrink-0 font-mono text-[11px]">{node.id}</span>
        </div>
        <h2 className="mt-0.5 text-lg font-semibold leading-snug">{node.title}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
          <span className={`rounded-full px-2 py-0.5 font-semibold ${lvl.pill}`}>
            Nivel {progress.mastery_level}/3
          </span>
          <span className="inline-flex items-center gap-1">
            <Dumbbell size={12} /> Reps {progress.training_reps}
          </span>
          <span className="inline-flex items-center gap-1">
            <Trophy size={12} /> Mejor {progress.best_score > 0 ? progress.best_score.toFixed(1) : '-'}
          </span>
          {cooling && (
            <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-800 dark:bg-amber-900/50 dark:text-amber-200">
              <Clock size={12} /> Cooldown · {formatRemaining(remaining)}
            </span>
          )}
        </div>
        <div className="mt-2 flex gap-1" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'story'}
            onClick={goStory}
            className={tabCls(tab === 'story')}
          >
            <BookOpen size={15} /> Historia
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'eval'}
            onClick={() => setTab('eval')}
            className={tabCls(tab === 'eval')}
          >
            <ClipboardCheck size={15} /> Evaluación a ciegas
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {tab === 'story' ? (
          <StoryTab
            courseId={courseId}
            node={node}
            worldMetaphor={worldMetaphor}
            onEvaluate={() => setTab('eval')}
            onRegenerateStory={onRegenerateStory}
          />
        ) : (
          <EvalTab
            node={node}
            progress={progress}
            onSubmit={onSubmit}
            onBackToStory={() => setTab('story')}
            onInProgressChange={handleProgress}
          />
        )}
      </div>

      {askLeave && (
        <ConfirmDialog
          title="Salir de la evaluación"
          message="Si vuelves a la historia se descartan tus respuestas de este intento. ¿Continuar?"
          confirmLabel="Volver a la historia"
          cancelLabel="Seguir evaluándome"
          onCancel={() => setAskLeave(false)}
          onConfirm={() => {
            setAskLeave(false)
            setTab('story')
          }}
        />
      )}
    </section>
  )
}
