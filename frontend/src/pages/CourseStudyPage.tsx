import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Home, MessageSquare, RotateCcw } from 'lucide-react'
import { inCooldown, type CooldownMode } from '../api/study'
import { selectCourses, useAppStore } from '../store/useAppStore'
import { useStudyStore } from '../store/useStudyStore'
import ChatDrawer from '../components/layout/ChatDrawer'
import ConfirmDialog from '../components/study/ConfirmDialog'
import EmptyCourse from '../components/study/EmptyCourse'
import SkillTree from '../components/study/SkillTree'
import StudyStation from '../components/study/StudyStation'
import { useNow } from '../components/study/studyUtils'

const MODES: { id: CooldownMode; label: string; hint: string }[] = [
  { id: 'semester', label: 'Modo Semestre', hint: 'Cooldown de 7 días entre validaciones' },
  { id: 'urgency', label: 'Modo Urgencia', hint: 'Cooldown de 30 s (demo)' },
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
    reset,
  } = useStudyStore()
  const [inProgress, setInProgress] = useState(false)
  const [pendingNode, setPendingNode] = useState<string | null>(null)
  const [askReset, setAskReset] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)

  const course = selectCourses({ career, profile, manualCourses }).find((c) => c.id === id)
  const lookupKey = course?.code ?? id

  useEffect(() => {
    if (!career) void loadCareer()
  }, [career, loadCareer])
  useEffect(() => setActiveCourse(id), [id, setActiveCourse])
  useEffect(() => {
    void load(lookupKey)
  }, [lookupKey, load])

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
    return <EmptyCourse name={course ? course.name : 'Ramo no encontrado'} code={course?.code ?? id} />
  }

  const node = tree.nodes.find((n) => n.id === selectedNodeId) ?? null
  const requestSelect = (nid: string) => {
    if (nid === selectedNodeId) return
    if (inProgress) setPendingNode(nid)
    else select(nid)
  }

  return (
    <div className="flex min-h-[calc(100vh-53px)] flex-col overflow-x-hidden lg:h-[calc(100vh-53px)] lg:min-h-0">
      {/* Barra del ramo */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-slate-200 px-4 py-2 dark:border-slate-800">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{tree.title}</div>
          <div className="font-mono text-[11px] text-slate-500">{tree.course_code}</div>
        </div>
        <div className="flex min-w-48 flex-1 flex-col gap-1">
          <div className="text-xs text-slate-600 dark:text-slate-300">
            Dominados {stats.mastered}/{stats.total} en 3/3 · Progreso del árbol {stats.pct}%
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
            <div className="h-full bg-emerald-500 transition-all" style={{ width: `${stats.pct}%` }} />
          </div>
        </div>
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
              className={`rounded px-2.5 py-1 text-xs font-medium ${
                cooldownMode === m.id
                  ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                  : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setChatOpen(true)}
          className="inline-flex items-center gap-1 rounded border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <MessageSquare size={13} /> Tutor del ramo
        </button>
        <button
          type="button"
          onClick={() => setAskReset(true)}
          title="Borra el progreso local de este ramo (solo demo)"
          className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          <RotateCcw size={13} /> Reiniciar progreso
        </button>
        <Link to="/" className="inline-flex items-center gap-1 text-xs underline">
          <Home size={13} /> Mi Malla
        </Link>
      </div>

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="h-[48vh] min-h-[340px] min-w-0 border-b border-slate-200 lg:h-auto lg:min-h-0 lg:basis-[58%] lg:border-b-0 lg:border-r dark:border-slate-800">
          <SkillTree tree={tree} selectedId={selectedNodeId} now={now} onSelect={requestSelect} />
        </div>
        <div className="min-h-0 min-w-0 flex-1 lg:basis-[42%]">
          {node ? (
            <StudyStation
              key={node.id}
              courseId={tree.course_id}
              node={node}
              progress={tree.progress[node.id]}
              worldMetaphor={tree.world_metaphor}
              now={now}
              onSubmit={(req) => submit(node.id, req)}
              onRegenerateStory={async () => {
                await regenerateNodeStory(node.id)
              }}
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
