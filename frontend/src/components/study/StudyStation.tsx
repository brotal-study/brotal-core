import { useCallback, useMemo, useState } from 'react'
import {
  BookOpen,
  ChevronDown,
  ChevronUp,
  ClipboardCheck,
  Clock,
  Dumbbell,
  FileText,
  FlaskConical,
  MessagesSquare,
  Mic,
  Trophy,
} from 'lucide-react'
import { inCooldown, type EvaluateResponse, type NodeProgress, type PackNode } from '../../api/study'
import { useStudyStore } from '../../store/useStudyStore'
import MarkdownView from '../common/MarkdownView'
import ConfirmDialog from './ConfirmDialog'
import EvalTab from './EvalTab'
import LanguageChatTab from './LanguageChatTab'
import QuickReferenceDrawer from './QuickReferenceDrawer'
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

type Tab = 'story' | 'eval' | 'chat'

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
  const tree = useStudyStore((s) => s.tree)
  const selectStoreNode = useStudyStore((s) => s.select)

  const isPractice = node.branch === 'practice'
  const isLanguageStudio = engineType === 'language_studio'
  const [tab, setTab] = useState<Tab>(isPractice ? 'eval' : 'story')
  const [inProgress, setInProgress] = useState(false)
  const [hasDraft, setHasDraft] = useState(false)
  const [pendingTab, setPendingTab] = useState<Tab | null>(null)
  const [quickRefOpen, setQuickRefOpen] = useState(false)
  const [briefingOpen, setBriefingOpen] = useState(false)

  const parentNodes = useMemo(
    () => (tree?.nodes ?? []).filter((n) => node.parent_ids.includes(n.id)),
    [tree, node.parent_ids],
  )

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

  const handleNavigateNode = useCallback(
    (nodeId: string) => {
      setQuickRefOpen(false)
      if (onSelectNextNode) {
        onSelectNextNode(nodeId)
      } else {
        onInProgressChange(false)
        selectStoreNode(nodeId)
      }
    },
    [onSelectNextNode, onInProgressChange, selectStoreNode],
  )

  const requestTabChange = (nextTab: Tab) => {
    if (nextTab === tab) return
    if (!isPractice && tab === 'eval' && inProgress) {
      setPendingTab(nextTab)
      return
    }
    setTab(nextTab)
  }

  const tabCls = (active: boolean) =>
    `inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${
      active
        ? 'border-slate-900 dark:border-slate-100'
        : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-slate-100'
    }`

  const briefingContent = (node.story_script || node.summary || '').trim()
  const briefingPreview = (node.summary || node.story_script || '').replace(/\s+/g, ' ').trim()
  const showPracticeTabs = isPractice && isLanguageStudio

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
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 pb-3 text-xs text-slate-600 dark:text-slate-300">
          <div className="flex flex-wrap items-center gap-2">
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

          {isPractice && (
            <button
              type="button"
              onClick={() => setQuickRefOpen(true)}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-indigo-300 bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-900 hover:bg-indigo-100 dark:border-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-200 dark:hover:bg-indigo-900/60"
            >
              <BookOpen size={13} />
              Apunte rápido ({parentNodes.length})
            </button>
          )}
        </div>

        {!isPractice && (
          <div className="flex flex-wrap gap-1" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'story'}
              onClick={() => requestTabChange('story')}
              className={tabCls(tab === 'story')}
            >
              <BookOpen size={15} /> Historia
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'eval'}
              onClick={() => requestTabChange('eval')}
              className={tabCls(tab === 'eval')}
            >
              <ClipboardCheck size={15} /> Evaluación a ciegas
            </button>
            {isLanguageStudio && (
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'chat'}
                onClick={() => requestTabChange('chat')}
                className={tabCls(tab === 'chat')}
              >
                <MessagesSquare size={15} /> Práctica Chat
              </button>
            )}
          </div>
        )}

        {showPracticeTabs && (
          <div className="flex flex-wrap gap-1" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'eval'}
              onClick={() => requestTabChange('eval')}
              className={tabCls(tab === 'eval')}
            >
              <ClipboardCheck size={15} /> Taller ({node.eval_prompts.length} retos)
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'chat'}
              onClick={() => requestTabChange('chat')}
              className={tabCls(tab === 'chat')}
            >
              <Mic size={15} /> Speaking / Simulacro
            </button>
          </div>
        )}
      </header>

      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-4 py-4 sm:px-5">
        {isPractice && briefingContent && (
          <div className="mb-4 rounded-md border border-slate-200 bg-slate-50/75 dark:border-slate-700 dark:bg-slate-800/45">
            <button
              type="button"
              aria-expanded={briefingOpen}
              onClick={() => setBriefingOpen((v) => !v)}
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs hover:bg-slate-100/80 dark:hover:bg-slate-800/70"
            >
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <FileText size={14} className="shrink-0 text-amber-600 dark:text-amber-400" />
                <span className="shrink-0 font-semibold text-slate-800 dark:text-slate-100">
                  Consigna / Briefing
                </span>
                {!briefingOpen && briefingPreview && (
                  <span className="min-w-0 truncate text-slate-500 dark:text-slate-400">
                    — {briefingPreview}
                  </span>
                )}
              </div>
              <span className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-slate-500 dark:text-slate-400">
                {briefingOpen ? 'Ocultar' : 'Ver consigna'}
                {briefingOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              </span>
            </button>
            {briefingOpen && (
              <div className="border-t border-slate-200 bg-white px-3.5 py-3 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200">
                <MarkdownView
                  content={briefingContent}
                  className="text-slate-700 dark:text-slate-200"
                />
              </div>
            )}
          </div>
        )}

        {!isPractice && tab === 'story' && (
          <StoryTab
            courseId={courseId}
            engineType={engineType}
            node={node}
            worldMetaphor={worldMetaphor}
            onEvaluate={() => setTab('eval')}
            onRegenerateStory={onRegenerateStory}
            onAskTutor={onAskTutor}
          />
        )}

        {isPractice ? (
          <div className={tab === 'eval' ? 'block' : 'hidden'}>
            <EvalTab
              courseId={courseId}
              engineType={engineType}
              node={node}
              progress={progress}
              nextNode={nextNode}
              onSelectNextNode={onSelectNextNode}
              parentNodes={parentNodes}
              onSelectNode={handleNavigateNode}
              onDraftChange={setHasDraft}
              onSubmit={onSubmit}
              onRegenerateQuestions={onRegenerateQuestions}
              onBackToStory={() => setQuickRefOpen(true)}
              onAskTutor={onAskTutor}
              onInProgressChange={handleProgress}
            />
          </div>
        ) : (
          tab === 'eval' && (
            <EvalTab
              courseId={courseId}
              engineType={engineType}
              node={node}
              progress={progress}
              nextNode={nextNode}
              onSelectNextNode={onSelectNextNode}
              parentNodes={parentNodes}
              onSelectNode={handleNavigateNode}
              onDraftChange={setHasDraft}
              onSubmit={onSubmit}
              onRegenerateQuestions={onRegenerateQuestions}
              onBackToStory={() => setTab('story')}
              onAskTutor={onAskTutor}
              onInProgressChange={handleProgress}
            />
          )
        )}

        {isLanguageStudio && (
          <div className={tab === 'chat' ? 'block' : 'hidden'}>
            <LanguageChatTab
              courseId={courseId}
              node={node}
              active={tab === 'chat'}
              defaultMode={isPractice ? 'exam_3parts' : 'missions'}
            />
          </div>
        )}
      </div>

      <QuickReferenceDrawer
        open={quickRefOpen}
        onClose={() => setQuickRefOpen(false)}
        parentNodes={parentNodes}
        onNavigateNode={handleNavigateNode}
        hasDraftInProgress={hasDraft}
      />

      {pendingTab !== null && (
        <ConfirmDialog
          title="Salir de la evaluación"
          message={
            pendingTab === 'chat'
              ? 'Si cambias a Práctica Chat se descartan tus respuestas de este intento. ¿Continuar?'
              : 'Si vuelves a la historia se descartan tus respuestas de este intento. ¿Continuar?'
          }
          confirmLabel={pendingTab === 'chat' ? 'Ir a Práctica Chat' : 'Volver a la historia'}
          cancelLabel="Seguir evaluándome"
          onCancel={() => setPendingTab(null)}
          onConfirm={() => {
            const target = pendingTab
            setPendingTab(null)
            setTab(target)
          }}
        />
      )}
    </section>
  )
}
