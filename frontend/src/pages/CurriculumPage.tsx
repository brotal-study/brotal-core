import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, BookOpen, CheckCircle2, ListChecks, MousePointerClick, Plus } from 'lucide-react'
import CourseCard from '../components/curriculum/CourseCard'
import CourseModal from '../components/curriculum/CourseModal'
import { categoryColor, missingPrereqs, progress, statusOf } from '../lib/curriculum'
import {
  DEFAULT_CATEGORIES,
  selectCourses,
  useAppStore,
  type CourseFilter,
} from '../store/useAppStore'

const FILTERS: { id: CourseFilter; label: string }[] = [
  { id: 'all', label: 'Todos' },
  { id: 'active', label: 'Cursando' },
  { id: 'pack', label: 'Con contenido / Pack' },
]

export default function CurriculumPage() {
  const navigate = useNavigate()
  const {
    profile,
    career,
    packs,
    installedPacks,
    courseProgress,
    statuses,
    setStatus,
    setActiveCourse,
    curriculumMode,
    setCurriculumMode,
    approveUpTo,
    manualCourses,
    addManualCourse,
    loadCareer,
  } = useAppStore()
  const [filter, setFilter] = useState<CourseFilter>('all')
  const [openId, setOpenId] = useState<string | null>(null)
  const [quickApprove, setQuickApprove] = useState(false)

  useEffect(() => {
    void loadCareer()
  }, [loadCareer])

  const courses = useMemo(
    () => selectCourses({ career, profile, manualCourses }),
    [career, profile, manualCourses],
  )
  const categories = career?.categories ?? DEFAULT_CATEGORIES
  const isCareer = profile?.mode === 'career'
  const prog = progress(courses, statuses)
  const open = courses.find((c) => c.id === openId) ?? null

  const activeCourses = useMemo(
    () => courses.filter((c) => statusOf(statuses, c.id) === 'active'),
    [courses, statuses],
  )

  const visible = courses.filter((c) => {
    if (filter === 'active') return statusOf(statuses, c.id) === 'active'
    if (filter === 'pack') return Boolean(packs[c.code] || installedPacks[c.code])
    return true
  })

  const goToStudy = (courseId: string) => {
    setActiveCourse(courseId)
    navigate(`/course/${encodeURIComponent(courseId)}`)
  }

  const card = (c: (typeof courses)[number]) => {
    const st = statusOf(statuses, c.id)
    const dimmed =
      isCareer &&
      curriculumMode === 'realistic' &&
      st !== 'passed' &&
      missingPrereqs(c, statuses).length > 0
     const hasContent = Boolean(installedPacks[c.code] || packs[c.code] || courseProgress[c.code]?.total)
    return (
      <CourseCard
        key={c.id}
        course={c}
        color={categoryColor(categories, c.category)}
        status={st}
        pack={packs[c.code]}
        progressSummary={courseProgress[c.code]}
        hasContent={hasContent}
        dimmed={dimmed}
        quickApproveMode={quickApprove}
        onOpen={() => {
          if (quickApprove) {
            setStatus(c.id, st === 'passed' ? 'pending' : 'passed')
          } else {
            setOpenId(c.id)
          }
        }}
        onStudy={() => goToStudy(c.id)}
      />
    )
  }

  const btn = (active: boolean) =>
    `rounded-md px-3 py-1.5 text-sm font-medium ${
      active
        ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
        : 'border border-slate-300 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800'
    }`

  if (isCareer && !career) {
    return <main className="p-6 text-sm text-slate-500">Cargando malla...</main>
  }

  const visibleSemesters =
    isCareer && career
      ? career.semesters
          .map((sem) => ({
            sem,
            list: visible.filter((c) => c.semester === sem.number),
          }))
          .filter(({ list }) => filter === 'all' || list.length > 0)
      : []

  return (
    <main className="flex flex-col gap-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold">{isCareer ? 'Mi Malla' : 'Tablero libre'}</h1>
        <p className="text-sm text-slate-500">
          {isCareer && career
            ? `${career.career.name} · ${career.university.short_name}${career.career.plan_ref ? ` · ${career.career.plan_ref}` : ''}`
            : `Ramos manuales de ${profile?.name ?? 'tu perfil'}`}
        </p>
      </div>

      <section
        className="rounded-lg border border-slate-200 p-4 dark:border-slate-800"
        aria-label="Progreso global"
      >
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
          <span className="text-2xl font-semibold">{prog.pct}% de avance</span>
          <span>
            Créditos aprobados{' '}
            <b>
              {prog.creditsPassed} / {prog.credits}
            </b>
          </span>
          <span>
            Ramos aprobados{' '}
            <b>
              {prog.passed} / {prog.total}
            </b>
          </span>
          {isCareer && <span className="text-xs text-slate-500">(sin contar ramos opcionales)</span>}
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
          <div
            className="h-full bg-emerald-600 dark:bg-emerald-500"
            style={{ width: `${prog.pct}%` }}
          />
        </div>
      </section>

      {activeCourses.length > 0 && (
        <section
          aria-label="Tus ramos en curso"
          className="flex flex-wrap items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50/70 px-3.5 py-2.5 text-xs dark:border-indigo-800/70 dark:bg-indigo-950/35"
        >
          <span className="inline-flex items-center gap-1.5 font-semibold text-indigo-900 dark:text-indigo-200">
            <BookOpen size={14} />
            Tus ramos en curso:
          </span>
          {activeCourses.map((ac) => (
            <button
              key={ac.id}
              type="button"
              onClick={() => goToStudy(ac.id)}
              className="inline-flex items-center gap-1.5 rounded-md border border-indigo-300 bg-white px-2.5 py-1 text-xs font-medium text-indigo-900 shadow-2xs hover:bg-indigo-100 dark:border-indigo-700 dark:bg-slate-900 dark:text-indigo-100 dark:hover:bg-indigo-900/60"
            >
              <span className="font-mono text-[11px]">{ac.code}</span>
              <span className="max-w-44 truncate">{ac.name}</span>
              <span className="inline-flex items-center gap-0.5 font-semibold text-indigo-600 dark:text-indigo-400">
                Estudiar <ArrowRight size={12} />
              </span>
            </button>
          ))}
        </section>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFilter(f.id)}
            className={btn(filter === f.id)}
          >
            {f.label}
          </button>
        ))}

        <button
          type="button"
          aria-pressed={quickApprove}
          onClick={() => setQuickApprove((v) => !v)}
          className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition ${
            quickApprove
              ? 'border-emerald-600 bg-emerald-600 text-white dark:border-emerald-500 dark:bg-emerald-500 dark:text-slate-950'
              : 'border-slate-300 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800'
          }`}
        >
          <MousePointerClick size={15} />
          Marcado rápido (1 clic)
        </button>

        {isCareer && career && (
          <>
            <span className="mx-1 hidden h-5 w-px bg-slate-300 sm:block dark:bg-slate-700" />
            <div className="inline-flex gap-1" role="group" aria-label="Modo de malla">
              <button
                type="button"
                onClick={() => setCurriculumMode('realistic')}
                className={btn(curriculumMode === 'realistic')}
              >
                Modo Carrera (Realista)
              </button>
              <button
                type="button"
                onClick={() => setCurriculumMode('free')}
                className={btn(curriculumMode === 'free')}
              >
                Modo Libre
              </button>
            </div>
            <label className="ml-auto inline-flex items-center gap-2 rounded-md border border-emerald-500/60 bg-emerald-50/70 px-2.5 py-1 text-sm font-medium text-emerald-950 dark:border-emerald-600/60 dark:bg-emerald-950/40 dark:text-emerald-200">
              <ListChecks size={16} className="text-emerald-600 dark:text-emerald-400" />
              <span className="hidden md:inline">Avance rápido:</span>
              <select
                value=""
                onChange={(e) => {
                  const n = Number(e.target.value)
                  if (n) approveUpTo(n)
                }}
                className="rounded border border-emerald-400 bg-white px-2 py-1 text-sm font-medium text-slate-900 dark:border-emerald-700 dark:bg-slate-900 dark:text-slate-100"
                aria-label="Marcar semestres anteriores aprobados"
              >
                <option value="">Aprobé hasta S...</option>
                {career.semesters.slice(0, -1).map((s) => (
                  <option key={s.number} value={s.number}>
                    Aprobé hasta {s.label}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
      </div>

      {quickApprove && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-emerald-400 bg-emerald-50 px-3.5 py-2 text-xs text-emerald-950 dark:border-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-200"
        >
          <span className="inline-flex items-center gap-1.5 font-medium">
            <CheckCircle2 size={15} className="text-emerald-600 dark:text-emerald-400" />
            Modo Marcado rápido activo: haz clic directo sobre cualquier tarjeta para alternar su estado Aprobado al instante.
          </span>
          <button
            type="button"
            onClick={() => setQuickApprove(false)}
            className="rounded border border-emerald-500/60 px-2 py-0.5 font-semibold hover:bg-emerald-100 dark:hover:bg-emerald-900"
          >
            Salir del modo rápido
          </button>
        </div>
      )}

      {isCareer && career ? (
        visibleSemesters.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
            No hay ramos que coincidan con el filtro seleccionado.{' '}
            <button
              type="button"
              onClick={() => setFilter('all')}
              className="font-medium text-indigo-600 underline dark:text-indigo-400"
            >
              Ver toda la malla
            </button>
          </div>
        ) : (
          <div className="-mx-4 overflow-x-auto px-4 pb-3 sm:-mx-6 sm:px-6">
            <div className="flex gap-3">
              {visibleSemesters.map(({ sem, list }) => (
                <section key={sem.number} className="flex w-60 shrink-0 flex-col gap-2">
                  <h2 className="text-sm font-semibold text-slate-500">
                    {sem.label}{' '}
                    <span className="font-normal">
                      · {sem.courses.reduce((a, c) => a + c.credits, 0)} cr.
                    </span>
                  </h2>
                  {list.map(card)}
                </section>
              ))}
            </div>
          </div>
        )
      ) : (
        <div className="flex flex-col gap-4">
          <ManualForm categories={categories} onAdd={(c) => setOpenId(addManualCourse(c))} />
          {visible.length === 0 ? (
            <p className="text-sm text-slate-500">
              Aún no hay ramos para mostrar con este filtro.
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{visible.map(card)}</div>
          )}
        </div>
      )}

      {open && (
        <CourseModal
          course={open}
          allCourses={courses}
          statuses={statuses}
          pack={packs[open.code]}
          onClose={() => setOpenId(null)}
        />
      )}
    </main>
  )
}

function ManualForm({
  categories,
  onAdd,
}: {
  categories: { id: string; label: string }[]
  onAdd: (c: { code: string; name: string; credits: number; category: string }) => void
}) {
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [credits, setCredits] = useState(3)
  const [category, setCategory] = useState(categories[0].id)
  const f =
    'rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900'
  return (
    <form
      className="flex flex-wrap items-end gap-2 rounded-lg border border-slate-200 p-3 dark:border-slate-800"
      onSubmit={(e) => {
        e.preventDefault()
        if (!name.trim()) return
        onAdd({ name: name.trim(), code: code.trim() || 'LIBRE', credits, category })
        setName('')
        setCode('')
      }}
    >
      <input
        className={`${f} min-w-48 flex-1`}
        placeholder="Nombre del ramo"
        value={name}
        onChange={(e) => setName(e.target.value)}
        aria-label="Nombre del ramo"
      />
      <input
        className={`${f} w-28`}
        placeholder="Código"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        aria-label="Código"
      />
      <input
        className={`${f} w-20`}
        type="number"
        min={0}
        max={30}
        value={credits}
        onChange={(e) => setCredits(Number(e.target.value))}
        aria-label="Créditos"
      />
      <select
        className={f}
        value={category}
        onChange={(e) => setCategory(e.target.value)}
        aria-label="Categoría"
      >
        {categories.map((c) => (
          <option key={c.id} value={c.id}>
            {c.label}
          </option>
        ))}
      </select>
      <button
        type="submit"
        className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900"
      >
        <Plus size={16} />
        Agregar ramo
      </button>
    </form>
  )
}
