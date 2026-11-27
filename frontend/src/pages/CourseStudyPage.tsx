import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { CalendarClock, Code2, FolderOpen, Home, Languages, MessageSquare, RotateCcw } from 'lucide-react'
import {
  getExamRoute,
  inCooldown,
  type CooldownMode,
  type CourseTree,
  type ExamRouteResponse,
  type PackNode,
} from '../api/study'
import { selectCourses, useAppStore } from '../store/useAppStore'
import { useStudyStore } from '../store/useStudyStore'
import ChatDrawer from '../components/layout/ChatDrawer'
import ConfirmDialog from '../components/study/ConfirmDialog'
import { CourseFilesModal } from '../components/study/CourseFilesPanel'
import EmptyCourse from '../components/study/EmptyCourse'
import ExamRouteModal from '../components/study/ExamRouteModal'
import IngestModal from '../components/study/IngestModal'
import SkillTree, { type TreeBranchFilter } from '../components/study/SkillTree'
import StudyStation from '../components/study/StudyStation'
import { useNow } from '../components/study/studyUtils'

function computeTopologicalNodes(nodes: PackNode[]): PackNode[] {
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const depthMemo: Record<string, number> = {}
  const depthOf = (id: string, seen: Set<string> = new Set()): number => {
    if (depthMemo[id] !== undefined) return depthMemo[id]
    if (seen.has(id)) return 0
    seen.add(id)
    const cur = byId[id]
    const validParents = (cur?.parent_ids ?? []).filter((p) => byId[p] !== undefined)
    return (depthMemo[id] = validParents.length
      ? 1 + Math.max(...validParents.map((p) => depthOf(p, new Set(seen))))
      : 0)
  }
  nodes.forEach((n) => depthOf(n.id))
  const indexMap = Object.fromEntries(nodes.map((n, idx) => [n.id, idx]))
  return [...nodes].sort((a, b) => {
    const da = depthMemo[a.id] ?? 0
    const db = depthMemo[b.id] ?? 0
    if (da !== db) return da - db
    return (indexMap[a.id] ?? 0) - (indexMap[b.id] ?? 0)
  })
}

function computeNextRecommendedNode(
  tree: CourseTree | null,
  currentNodeId: string | null,
): PackNode | null {
  if (!tree || !currentNodeId) return null
  const topoTheory = computeTopologicalNodes(tree.nodes.filter((n) => n.branch === 'theory'))
  const topoPractice = computeTopologicalNodes(tree.nodes.filter((n) => n.branch === 'practice'))

  const isPending = (n: PackNode) => (tree.progress[n.id]?.mastery_level ?? 0) < 3

  // Si estamos en un nodo theory, priorizar el siguiente theory pendiente después del actual en orden topológico
  const currentTheoryIdx = topoTheory.findIndex((n) => n.id === currentNodeId)
  if (currentTheoryIdx !== -1) {
    const afterCurrent = topoTheory
      .slice(currentTheoryIdx + 1)
      .find((n) => n.id !== currentNodeId && isPending(n))
    if (afterCurrent) return afterCurrent
  }

  const anyPendingTheory = topoTheory.find((n) => n.id !== currentNodeId && isPending(n))
  if (anyPendingTheory) return anyPendingTheory

  const currentPracticeIdx = topoPractice.findIndex((n) => n.id === currentNodeId)
  if (currentPracticeIdx !== -1) {
    const afterPractice = topoPractice
      .slice(currentPracticeIdx + 1)
      .find((n) => n.id !== currentNodeId && isPending(n))
    if (afterPractice) return afterPractice
  }

  const anyPendingPractice = topoPractice.find((n) => n.id !== currentNodeId && isPending(n))
  if (anyPendingPractice) return anyPendingPractice

  // Si todos los demás están en 3/3, sugerir el siguiente en orden topológico general
  const allTopo = [...topoTheory, ...topoPractice]
  const curIdx = allTopo.findIndex((n) => n.id === currentNodeId)
  if (curIdx !== -1 && allTopo.length > 1) {
    return allTopo[(curIdx + 1) % allTopo.length]
  }
  return allTopo.find((n) => n.id !== currentNodeId) ?? null
}

const MODES: { id: CooldownMode; label: string; hint: string; activeNote: string }[] = [
  {
    id: 'semester',
    label: 'Repaso Espaciado (7d)',
    hint: 'Cooldown de 7 días entre validaciones',
    activeNote: 'Sube nivel 0/3->3/3 tras 7 días',
  },
  {
    id: 'urgency',
    label: 'Repaso Rápido (examen)',
    hint: 'Modo examen: 30 s entre validaciones',
    activeNote: 'Modo examen: 30 s entre validaciones',
  },
]

const BRANCH_FILTERS: { id: TreeBranchFilter; label: string }[] = [
  { id: 'all', label: 'Completo' },
  { id: 'theory', label: 'Teoría' },
  { id: 'practice', label: 'Práctica' },
]

export default function CourseStudyPage() {
  const { courseId = '' } = useParams()
  const id = decodeURIComponent(courseId)
  const { career, profile, manualCourses, loadCareer, setActiveCourse } = useAppStore()
  const {
    tree,
    status,
    selectedNodeId,
    cooldownMode,
    setCooldownMode,
    load,
    select,
    submit,
    regenerateNodeStory,
    regenerateNodeQuestions,
    reset,
  } = useStudyStore()
  const [inProgress, setInProgress] = useState(false)
  const [pendingNode, setPendingNode] = useState<string | null>(null)
  const [askReset, setAskReset] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [chatPrompt, setChatPrompt] = useState<string | null>(null)
  const [chatBanner, setChatBanner] = useState<string | null>(null)
  const [chatAutoSendTrigger, setChatAutoSendTrigger] = useState(0)
  const [filesOpen, setFilesOpen] = useState(false)
  const [examRouteOpen, setExamRouteOpen] = useState(false)
  const [savedExamRoute, setSavedExamRoute] = useState<ExamRouteResponse | null>(null)
  const [ingestOpen, setIngestOpen] = useState(false)
  const [filesRefresh, setFilesRefresh] = useState(0)
  const [branchFilter, setBranchFilter] = useState<TreeBranchFilter>('all')

  const course = selectCourses({ career, profile, manualCourses }).find((c) => c.id === id)
  const lookupKey = course?.code ?? id

  useEffect(() => {
    if (!career) void loadCareer()
  }, [career, loadCareer])
  useEffect(() => setActiveCourse(id), [id, setActiveCourse])
  useEffect(() => {
    void load(lookupKey)
  }, [lookupKey, load])
  useEffect(() => {
    if (!tree?.course_id) {
      setSavedExamRoute(null)
      return
    }
    let active = true
    void getExamRoute(tree.course_id)
      .then((r) => {
        if (active) setSavedExamRoute(r)
      })
      .catch(() => {
        if (active) setSavedExamRoute(null)
      })
    return () => {
      active = false
    }
  }, [tree?.course_id])

  const anyCooldown = tree ? Object.values(tree.progress).some((p) => inCooldown(p)) : false
  const now = useNow(anyCooldown)

  const stats = useMemo(() => {
    if (!tree) return { mastered: 0, total: 0, pct: 0 }
    const total = tree.nodes.length
    const levels = Object.values(tree.progress).map((p) => p.mastery_level)
    return {
      mastered: levels.filter((l) => l === 3).length,
      total,
      pct: total ? Math.round((levels.reduce((a, b) => a + b, 0) / (3 * total)) * 100) : 0,
    }
  }, [tree])

  if (status === 'loading' || status === 'idle') {
    return <main className="p-6 text-sm text-slate-500">Cargando árbol...</main>
  }
  if (status === 'empty' || !tree) {
    return (
      <EmptyCourse name={course ? course.name : 'Ramo no encontrado'} code={course?.code ?? id} />
    )
  }

  const node = tree.nodes.find((n) => n.id === selectedNodeId) ?? null
  const nextRecommendedNode = computeNextRecommendedNode(tree, selectedNodeId)
  const activeModeMeta = MODES.find((m) => m.id === cooldownMode) ?? MODES[0]

  const requestSelect = (nid: string) => {
    if (nid === selectedNodeId) return
    if (inProgress) setPendingNode(nid)
    else select(nid)
  }

  const handleSelectNextNode = (nid: string) => {
    const target = tree.nodes.find((n) => n.id === nid)
    if (target && branchFilter !== 'all' && branchFilter !== target.branch) {
      setBranchFilter('all')
    }
    setInProgress(false)
    select(nid)
  }

  const openContextualTutor = (ctx: { prompt: string; banner: string; autoSend?: boolean }) => {
    setChatPrompt(ctx.prompt)
    setChatBanner(ctx.banner)
    if (ctx.autoSend) {
      setChatAutoSendTrigger((n) => n + 1)
    } else {
      setChatAutoSendTrigger(0)
    }
    setChatOpen(true)
  }

  return (
    <div className="flex min-h-[calc(100vh-53px)] w-full max-w-full flex-col overflow-x-hidden lg:h-[calc(100vh-53px)] lg:min-h-0">
      {/* Barra del ramo */}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-slate-200 px-3 py-2 sm:px-4 dark:border-slate-800">
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <div className="min-w-0 max-w-xs sm:max-w-sm">
            <div className="flex items-center gap-2">
              <div className="truncate text-sm font-semibold">{tree.title}</div>
              {tree.engine_type === 'code_lab' && (
                <span className="inline-flex shrink-0 items-center gap-1 rounded border border-indigo-300 bg-indigo-50 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-800 dark:border-indigo-700/80 dark:bg-indigo-950/60 dark:text-indigo-200">
                  <Code2 size={11} />
                  Code Lab
                </span>
              )}
              {tree.engine_type === 'language_studio' && (
                <span className="inline-flex shrink-0 items-center gap-1 rounded border border-teal-300 bg-teal-50 px-1.5 py-0.5 text-[10px] font-semibold text-teal-900 dark:border-teal-700/80 dark:bg-teal-950/60 dark:text-teal-200">
                  <Languages size={11} />
                  Language Studio
                </span>
              )}
            </div>
            <div className="font-mono text-[11px] text-slate-500">{tree.course_code}</div>
          </div>

          <div className="flex w-44 flex-col gap-1 sm:w-52">
            <div className="truncate text-[11px] text-slate-600 dark:text-slate-300">
              Dominados {stats.mastered}/{stats.total} (3/3) · {stats.pct}%
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
              <div
                className="h-full bg-emerald-500 transition-all"
                style={{ width: `${stats.pct}%` }}
              />
            </div>
          </div>

          <div
            className="inline-flex rounded-md border border-slate-300 p-0.5 dark:border-slate-600"
            role="group"
            aria-label="Filtro de ramas del árbol"
          >
            {BRANCH_FILTERS.map((bf) => (
              <button
                key={bf.id}
                type="button"
                aria-pressed={branchFilter === bf.id}
                onClick={() => setBranchFilter(bf.id)}
                className={`rounded px-2 py-1 text-xs font-medium ${
                  branchFilter === bf.id
                    ? 'bg-indigo-600 text-white dark:bg-indigo-500'
                    : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                }`}
              >
                {bf.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <div
              className="inline-flex rounded-md border border-slate-300 p-0.5 dark:border-slate-600"
              role="group"
              aria-label="Modo de cooldown"
            >
              {MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  title={m.hint}
                  aria-pressed={cooldownMode === m.id}
                  onClick={() => setCooldownMode(m.id)}
                  className={`rounded px-2 py-1 text-xs font-medium ${
                    cooldownMode === m.id
                      ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                      : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
            <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">
              {activeModeMeta.activeNote}
            </span>
          </div>

          <button
            type="button"
            onClick={() => setExamRouteOpen(true)}
            className={`inline-flex items-center gap-1 rounded border px-2.5 py-1 text-xs font-medium ${
              savedExamRoute
                ? 'border-indigo-400 bg-indigo-50 text-indigo-900 hover:bg-indigo-100 dark:border-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-200 dark:hover:bg-indigo-950'
                : 'border-slate-300 text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800'
            }`}
          >
            <CalendarClock size={13} />
            Ruta de examen
            {savedExamRoute && (
              <span className="rounded bg-indigo-600 px-1 py-0.2 font-mono text-[10px] font-semibold text-white dark:bg-indigo-500">
                {savedExamRoute.days_left === 0 ? 'Hoy' : `${savedExamRoute.days_left}d`}
              </span>
            )}
          </button>

          <button
            type="button"
            onClick={() => setFilesOpen(true)}
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <FolderOpen size={13} /> Archivos
          </button>

          <button
            type="button"
            onClick={() => {
              setChatPrompt(null)
              setChatBanner(null)
              setChatAutoSendTrigger(0)
              setChatOpen(true)
            }}
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <MessageSquare size={13} /> Tutor del ramo
          </button>

          <button
            type="button"
            onClick={() => setAskReset(true)}
            title="Borra el progreso local de este ramo"
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <RotateCcw size={13} /> Reiniciar progreso
          </button>

          <Link to="/" className="inline-flex items-center gap-1 text-xs font-medium underline">
            <Home size={13} /> Mi Malla
          </Link>
        </div>
      </div>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col lg:flex-row">
        <div className="h-[48vh] min-h-[340px] min-w-0 border-b border-slate-200 lg:h-auto lg:min-h-0 lg:basis-[56%] lg:border-b-0 lg:border-r dark:border-slate-800">
          <SkillTree
            tree={tree}
            selectedId={selectedNodeId}
            branchFilter={branchFilter}
            now={now}
            onSelect={requestSelect}
          />
        </div>
        <div className="min-h-0 min-w-0 flex-1 overflow-x-hidden lg:basis-[44%]">
          {node ? (
            <StudyStation
              key={node.id}
              courseId={tree.course_id}
              engineType={tree.engine_type}
              node={node}
              progress={tree.progress[node.id]}
              nextNode={nextRecommendedNode}
              onSelectNextNode={handleSelectNextNode}
              worldMetaphor={tree.world_metaphor}
              now={now}
              onSubmit={(req) => submit(node.id, req)}
              onRegenerateStory={async () => {
                await regenerateNodeStory(node.id)
              }}
              onRegenerateQuestions={async () => {
                await regenerateNodeQuestions(node.id)
              }}
              onAskTutor={openContextualTutor}
              onInProgressChange={setInProgress}
            />
          ) : (
            <p className="p-6 text-sm text-slate-500">Selecciona un nodo del árbol.</p>
          )}
        </div>
      </div>

      <ChatDrawer
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        courseId={tree.course_id}
        courseTitle={tree.title}
        nodeId={selectedNodeId}
        nodeTitle={node?.title ?? null}
        initialPrompt={chatPrompt}
        contextBanner={chatBanner}
        autoSendTrigger={chatAutoSendTrigger}
        onSelectNode={requestSelect}
      />

      <ExamRouteModal
        open={examRouteOpen}
        onClose={() => setExamRouteOpen(false)}
        tree={tree}
        cooldownMode={cooldownMode}
        onChangeCooldownMode={setCooldownMode}
        onSelectNode={handleSelectNextNode}
        onAskTutor={openContextualTutor}
        onRouteUpdated={setSavedExamRoute}
      />

      <CourseFilesModal
        open={filesOpen}
        onClose={() => setFilesOpen(false)}
        courseId={tree.course_code || tree.course_id}
        courseTitle={tree.title}
        hasTree={tree.nodes.length > 0}
        refreshTrigger={filesRefresh}
        onOpenIngest={() => {
          setFilesOpen(false)
          setIngestOpen(true)
        }}
        onCourseCleared={() => {
          void useAppStore.getState().hydrate()
          void load(lookupKey)
        }}
      />

      <IngestModal
        open={ingestOpen}
        onClose={() => setIngestOpen(false)}
        defaultCode={tree.course_code}
        defaultTitle={tree.title}
        careerId={profile?.careerId ?? null}
        onIngested={() => {
          setFilesRefresh((n) => n + 1)
          void load(lookupKey)
        }}
      />

      {pendingNode && (
        <ConfirmDialog
          title="Cambiar de nodo"
          message="Tienes una evaluación en curso. Si cambias de nodo se descartan tus respuestas."
          confirmLabel="Cambiar de nodo"
          cancelLabel="Quedarme"
          onCancel={() => setPendingNode(null)}
          onConfirm={() => {
            select(pendingNode)
            setPendingNode(null)
            setInProgress(false)
          }}
        />
      )}
      {askReset && (
        <ConfirmDialog
          title="Reiniciar progreso"
          message="Se borran niveles, Reps y mejores notas de este ramo en este navegador."
          confirmLabel="Reiniciar"
          onCancel={() => setAskReset(false)}
          onConfirm={() => {
            setAskReset(false)
            setInProgress(false)
            void reset()
          }}
        />
      )}
    </div>
  )
}
