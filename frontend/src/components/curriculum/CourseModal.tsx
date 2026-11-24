import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Check, Download, FilePlus2, Trash2, X } from 'lucide-react'
import type { Course, CourseStatus, PackSummary } from '../../api/types'
import { STATUS_LABEL, useAppStore } from '../../store/useAppStore'
import { statusOf, type StatusMap } from '../../lib/curriculum'
import IngestModal from '../study/IngestModal'

interface Props {
  course: Course
  allCourses: Course[]
  statuses: StatusMap
  pack?: PackSummary
  onClose: () => void
}

const OPTIONS: { value: CourseStatus; label: string }[] = [
  { value: 'pending', label: STATUS_LABEL.pending },
  { value: 'active', label: STATUS_LABEL.active },
  { value: 'passed', label: STATUS_LABEL.passed },
  { value: 'archived', label: 'Archivar archivos' },
]

export default function CourseModal({ course, allCourses, statuses, pack, onClose }: Props) {
  const navigate = useNavigate()
  const {
    profile,
    setStatus,
    install,
    installedPacks,
    setActiveCourse,
    removeManualCourse,
    curriculumMode,
  } = useAppStore()
  const [busy, setBusy] = useState(false)
  const [ingestOpen, setIngestOpen] = useState(false)
  const status = statusOf(statuses, course.id)
  const installed = installedPacks[course.code]
  const prereqs = course.prerequisites.map((code) => ({
    code,
    name: allCourses.find((c) => c.code === code)?.name ?? code,
    ok: statusOf(statuses, code) === 'passed',
  }))
  const missing = prereqs.filter((p) => !p.ok)

  const enter = () => {
    setActiveCourse(course.id)
    navigate(`/course/${encodeURIComponent(course.id)}`)
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <aside
        role="dialog"
        aria-label={course.name}
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-md flex-col gap-5 overflow-y-auto border-l border-slate-200 bg-white p-5 shadow-xl dark:border-slate-800 dark:bg-slate-900"
      >
        <header className="flex items-start justify-between gap-3">
          <div>
            <p className="font-mono text-xs text-slate-500">
              {course.code} · {course.credits} créditos
              {course.semester ? ` · S${course.semester}` : ''}
            </p>
            <h2 className="text-lg font-semibold leading-snug">{course.name}</h2>
          </div>
          <button
            type="button"
            aria-label="Cerrar"
            onClick={onClose}
            className="rounded p-1.5 hover:bg-slate-200 dark:hover:bg-slate-800"
          >
            <X size={18} />
          </button>
        </header>

        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Prerrequisitos</h3>
          {prereqs.length === 0 ? (
            <p className="text-sm text-slate-500">Sin prerrequisitos.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {prereqs.map((p) => (
                <li key={p.code} className="flex items-center gap-2">
                  {p.ok ? (
                    <Check size={14} className="text-emerald-600 dark:text-emerald-400" />
                  ) : (
                    <X size={14} className="text-amber-600 dark:text-amber-400" />
                  )}
                  <span className="font-mono text-xs">{p.code}</span>
                  <span className="truncate">{p.name}</span>
                  <span className="ml-auto text-xs text-slate-500">{p.ok ? 'listo' : 'falta'}</span>
                </li>
              ))}
            </ul>
          )}
          {missing.length > 0 && curriculumMode === 'realistic' && (
            <p className="mt-2 text-xs text-slate-500">
              Te faltan {missing.length} prerrequisito(s). Puedes abrir y estudiar este ramo igual.
            </p>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Estado</h3>
          <div className="grid grid-cols-2 gap-2">
            {OPTIONS.map((o) => (
              <button
                key={o.value}
                type="button"
                onClick={() => setStatus(course.id, o.value)}
                className={`rounded-md border px-3 py-1.5 text-sm ${
                  status === o.value
                    ? 'border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900'
                    : 'border-slate-300 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800'
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Pack de estudio</h3>
          {pack ? (
            <div className="space-y-2 text-sm">
              <p className="font-medium">{pack.title}</p>
              <p className="text-xs text-slate-500">
                Creado {pack.metadata.created_year} · Act. {pack.metadata.updated_year} · v{pack.metadata.version}
                <br />
                Autor: {pack.metadata.authors.join(', ')} · {pack.node_count} nodos · {pack.metadata.license}
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy || !!installed}
                  onClick={async () => {
                    setBusy(true)
                    try {
                      await install(course.code, pack.id)
                    } finally {
                      setBusy(false)
                    }
                  }}
                  className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-60 dark:border-slate-700 dark:hover:bg-slate-800"
                >
                  {installed ? <Check size={16} /> : <Download size={16} />}
                  {installed ? `Pack activo (v${installed})` : 'Instalar y activar pack'}
                </button>
                <button
                  type="button"
                  onClick={() => setIngestOpen(true)}
                  className="inline-flex items-center gap-1.5 rounded-md border border-dashed border-slate-400 px-2.5 py-1.5 text-xs hover:bg-slate-100 dark:hover:bg-slate-800"
                >
                  <FilePlus2 size={14} /> Crear desde tus archivos (PDF/PPTX)
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-2 text-sm">
              <p className="text-slate-500">No hay un pack comunitario para este ramo.</p>
              <button
                type="button"
                onClick={() => setIngestOpen(true)}
                className="inline-flex items-center gap-2 rounded-md border border-dashed border-slate-400 px-3 py-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <FilePlus2 size={16} />
                Crear desde tus archivos (PDF/PPTX)
              </button>
            </div>
          )}
        </section>

        <div className="mt-auto flex flex-col gap-2">
          <button
            type="button"
            onClick={enter}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
          >
            Entrar al Árbol de Estudio
            <ArrowRight size={16} />
          </button>
          {course.manual && (
            <button
              type="button"
              onClick={() => {
                removeManualCourse(course.id)
                onClose()
              }}
              className="inline-flex items-center justify-center gap-2 text-xs text-slate-500 hover:text-red-600"
            >
              <Trash2 size={14} />
              Eliminar ramo
            </button>
          )}
        </div>
      </aside>
      <IngestModal
        open={ingestOpen}
        onClose={() => setIngestOpen(false)}
        defaultCode={course.code}
        defaultTitle={course.name}
        careerId={profile?.careerId ?? null}
      />
    </div>
  )
}
