import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import { selectCourses, useAppStore } from '../../store/useAppStore'

/** Selector rapido (Ctrl/Cmd+K) de ramos en estado Cursando. */
export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate()
  const { career, profile, manualCourses, statuses, setActiveCourse } = useAppStore()
  const [q, setQ] = useState('')
  const [idx, setIdx] = useState(0)
  const input = useRef<HTMLInputElement>(null)

  const list = useMemo(() => {
    const active = selectCourses({ career, profile, manualCourses }).filter((c) => statuses[c.id] === 'active')
    const t = q.trim().toLowerCase()
    return t ? active.filter((c) => `${c.code} ${c.name}`.toLowerCase().includes(t)) : active
  }, [career, profile, manualCourses, statuses, q])

  useEffect(() => {
    if (open) {
      setQ('')
      setIdx(0)
      setTimeout(() => input.current?.focus(), 0)
    }
  }, [open])

  if (!open) return null

  const go = (id: string) => {
    setActiveCourse(id)
    navigate(`/course/${encodeURIComponent(id)}`)
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 pt-24" onClick={onClose}>
      <div
        role="dialog"
        aria-label="Buscar ramo cursando"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900"
      >
        <div className="flex items-center gap-2 border-b border-slate-200 px-3 dark:border-slate-700">
          <Search size={16} className="text-slate-500" />
          <input
            ref={input}
            value={q}
            onChange={(e) => { setQ(e.target.value); setIdx(0) }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') onClose()
              else if (e.key === 'ArrowDown') { e.preventDefault(); setIdx((i) => Math.min(i + 1, list.length - 1)) }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)) }
              else if (e.key === 'Enter' && list[idx]) go(list[idx].id)
            }}
            placeholder="Buscar ramo cursando..."
            className="w-full bg-transparent py-3 text-sm outline-none"
          />
        </div>
        <ul className="max-h-72 overflow-y-auto p-1">
          {list.map((c, i) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => go(c.id)}
                onMouseEnter={() => setIdx(i)}
                className={`flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm ${i === idx ? 'bg-slate-100 dark:bg-slate-800' : ''}`}
              >
                <span className="font-mono text-xs text-slate-500">{c.code}</span>
                <span className="truncate">{c.name}</span>
              </button>
            </li>
          ))}
          {list.length === 0 && <li className="px-3 py-4 text-sm text-slate-500">No hay ramos cursando que coincidan.</li>}
        </ul>
      </div>
    </div>
  )
}
