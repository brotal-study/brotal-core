import { useCallback, useState } from 'react'
import { BookOpen, ClipboardCheck, Clock, Dumbbell, FlaskConical, Trophy } from 'lucide-react'
import { inCooldown, type EvaluateResponse, type NodeProgress, type PackNode } from '../../api/study'
import ConfirmDialog from './ConfirmDialog'
import EvalTab from './EvalTab'
import StoryTab from './StoryTab'
import { formatRemaining, LEVEL_STYLE } from './studyUtils'

interface Props {
  courseId: string
  engineType?: string
  node: PackNode
  progress: NodeProgress
  nextNode?: PackNode | null
  onSelectNextNode?: (nodeId: string) => void
  worldMetaphor: string | null
  now: number
  onSubmit: (req: {
    answers: { prompt_id: string; text: string }[]
    covered_points?: string[]
  }) => Promise<EvaluateResponse>
  onRegenerateStory: () => Promise<void>
  onRegenerateQuestions: () => Promise<void>
  onAskTutor: (ctx: { prompt: string; banner: string; autoSend?: boolean }) => void
  onInProgressChange: (v: boolean) => void
}

type Tab = 'story' | 'eval'

/** Se monta con `key={node.id}`: al cambiar de nodo el estado local se reinicia. */
export default function StudyStation({
  courseId,
  engineType,
  node,
  progress,
  nextNode = null,
  onSelectNextNode,
  worldMetaphor,
  now,
  onSubmit,
  onRegenerateStory,
  onRegenerateQuestions,
  onAskTutor,
  onInProgressChange,
}: Props) {
  const isPractice = node.branch === 'practice'
  const [tab, setTab] = useState<Tab>(isPractice ? 'eval' : 'story')
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
    <section className="flex h-full min-h-0 min-w-0 max-w-full flex-col overflow-x-hidden">
      <header className="min-w-0 border-b border-slate-200 px-4 pt-3.5 sm:px-5 sm:pt-4 dark:border-slate-800">
        <div className="flex items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
          <span className="inline-flex min-w-0 items-center gap-1.5 truncate">
            {isPractice && (
              <span className="inline-flex shrink-0 items-center gap-1 rounded border border-amber-300 bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900 dark:border-amber-700 dark:bg-amber-900/60 dark:text-amber-200">
                <FlaskConical size={11} /> Examen / Práctica
              </span>
            )}
            <span className="truncate">{node.block}</span>
          </span>
          <span className="shrink-0 font-mono text-[11px]">{node.id}</span>
        </div>
        <h2 className="mt-1 break-words text-lg font-semibold leading-snug">{node.title}</h2>
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
        <div className="mt-2 flex flex-wrap gap-1" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'story'}
            onClick={goStory}
            className={tabCls(tab === 'story')}
          >
            <BookOpen size={15} /> {isPractice ? 'Caso / Enunciado' : 'Historia'}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'eval'}
            onClick={() => setTab('eval')}
            className={tabCls(tab === 'eval')}
          >
            <ClipboardCheck size={15} /> {isPractice ? 'Evaluación / Desafío' : 'Evaluación a ciegas'}
          </button>
        </div>
      </header>

      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-4 py-4 sm:px-5">
        {tab === 'story' ? (
          <StoryTab
            courseId={courseId}
            engineType={engineType}
            node={node}
            worldMetaphor={worldMetaphor}
            onEvaluate={() => setTab('eval')}
            onRegenerateStory={onRegenerateStory}
            onAskTutor={onAskTutor}
          />
        ) : (
          <EvalTab
            courseId={courseId}
            engineType={engineType}
            node={node}
            progress={progress}
            nextNode={nextNode}
            onSelectNextNode={onSelectNextNode}
            onSubmit={onSubmit}
            onRegenerateQuestions={onRegenerateQuestions}
            onBackToStory={() => setTab('story')}
            onAskTutor={onAskTutor}
            onInProgressChange={handleProgress}
          />
        )}
      </div>

      {askLeave && (
        <ConfirmDialog
          title="Salir de la evaluación"
          message="Si vuelves a la historia se descartan tus respuestas de este intento. ¿Continuar?"
          confirmLabel={isPractice ? 'Ver Caso / Enunciado' : 'Volver a la historia'}
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
