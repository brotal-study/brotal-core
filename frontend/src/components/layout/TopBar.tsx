import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Home, MessageSquare, Settings } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import ThemeToggle from './ThemeToggle'
import CommandPalette from './CommandPalette'
import AiSettingsModal from './AiSettingsModal'
import ChatDrawer from './ChatDrawer'
import { selectCourses, useAppStore } from '../../store/useAppStore'
import { useStudyStore } from '../../store/useStudyStore'

export default function TopBar() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { career, profile, manualCourses, statuses, setActiveCourse, loadCareer } = useAppStore()
  const { tree, selectedNodeId } = useStudyStore()
  const [menu, setMenu] = useState(false)
  const [palette, setPalette] = useState(false)
  const [aiSettings, setAiSettings] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (profile && !career && profile.mode === 'career') void loadCareer()
  }, [profile, career, loadCareer])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setMenu(false)
        setPalette((p) => !p)
      }
    }
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenu(false)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
    }
  }, [])

  const all = useMemo(() => selectCourses({ career, profile, manualCourses }), [career, profile, manualCourses])
  const active = all.filter((c) => statuses[c.id] === 'active')
  const routeId = pathname.startsWith('/course/') ? decodeURIComponent(pathname.slice(8)) : null
  const isInCourse = routeId !== null
  const current = isInCourse ? all.find((c) => c.id === routeId) : undefined
  const activeNode = isInCourse ? (tree?.nodes.find((n) => n.id === selectedNodeId) ?? null) : null
  const chatCourseId = isInCourse ? (tree?.course_id ?? current?.code ?? routeId) : null

  useEffect(() => {
    if (!isInCourse) setChatOpen(false)
  }, [isInCourse])

  const item = 'rounded px-2 py-1 hover:bg-slate-200 dark:hover:bg-slate-800'
  return (
    <header className="flex items-center gap-3 border-b border-slate-200 px-4 py-2 dark:border-slate-800">
      <Link to="/" className={`flex items-center gap-2 ${item}`}>
        <Home size={18} />
        <span>Malla</span>
      </Link>
      <span className="text-slate-400">|</span>
      <div ref={ref} className="relative">
        <button type="button" onClick={() => setMenu((m) => !m)} aria-expanded={menu} className={`flex items-center gap-2 ${item}`}>
          <span>
            {isInCourse ? (current ? current.name : tree ? tree.title : 'Ramo actual') : 'Cambiar ramo'}
          </span>
          <ChevronDown size={16} />
        </button>
        {menu && (
          <div className="absolute left-0 top-full z-30 mt-1 w-72 rounded-lg border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-900">
            {active.length === 0 && <p className="px-3 py-2 text-sm text-slate-500">No tienes ramos en estado Cursando.</p>}
            {active.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  setActiveCourse(c.id)
                  setMenu(false)
                  navigate(`/course/${encodeURIComponent(c.id)}`)
                }}
                className={`flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${c.id === routeId ? 'bg-slate-100 dark:bg-slate-800' : ''}`}
              >
                <span className="font-mono text-xs text-slate-500">{c.code}</span>
                <span className="truncate">{c.name}</span>
              </button>
            ))}
            <div className="mt-1 border-t border-slate-200 pt-1 dark:border-slate-700">
              <Link to="/" onClick={() => setMenu(false)} className="block rounded px-3 py-2 text-sm hover:bg-slate-100 dark:hover:bg-slate-800">
                + Gestionar ramos / Ir a Malla
              </Link>
            </div>
          </div>
        )}
      </div>
      <button type="button" onClick={() => setPalette(true)} className="hidden items-center gap-1 rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-500 sm:flex dark:border-slate-700">
        Ctrl+K
      </button>
      <div className="ml-auto flex items-center gap-1">
        {chatCourseId && (
          <button
            type="button"
            onClick={() => setChatOpen(true)}
            className="inline-flex items-center gap-1.5 rounded border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
          >
            <MessageSquare size={14} />
            <span>Chat Tutor</span>
          </button>
        )}
        {profile && <span className="hidden px-1 text-sm text-slate-500 sm:inline">{profile.name}</span>}
        <button
          type="button"
          onClick={() => setAiSettings(true)}
          aria-label="Configuración de IA"
          title="Configuración de IA (Groq / Gemini / Ollama)"
          className="rounded p-2 hover:bg-slate-200 dark:hover:bg-slate-800"
        >
          <Settings size={18} />
        </button>
        <ThemeToggle />
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
      <AiSettingsModal open={aiSettings} onClose={() => setAiSettings(false)} />
      {chatCourseId && (
        <ChatDrawer
          open={chatOpen}
          onClose={() => setChatOpen(false)}
          courseId={chatCourseId}
          courseTitle={tree?.title ?? current?.name ?? chatCourseId}
          nodeId={selectedNodeId}
          nodeTitle={activeNode?.title ?? null}
        />
      )}
    </header>
  )
}
