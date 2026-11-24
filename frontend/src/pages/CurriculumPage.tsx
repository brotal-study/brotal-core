import { useEffect, useMemo, useState } from 'react'
import { ListChecks, Plus } from 'lucide-react'
import CourseCard from '../components/curriculum/CourseCard'
import CourseModal from '../components/curriculum/CourseModal'
import { categoryColor, missingPrereqs, progress, statusOf } from '../lib/curriculum'
import { DEFAULT_CATEGORIES, selectCourses, useAppStore, type CourseFilter } from '../store/useAppStore'

const FILTERS: { id: CourseFilter; label: string }[] = [
  { id: 'all', label: 'Todos' },
  { id: 'active', label: 'Cursando' },
  { id: 'pack', label: 'Con Pack disponible' },
]

export default function CurriculumPage() {
  const { profile, career, packs, statuses, curriculumMode, setCurriculumMode, approveUpTo, manualCourses, addManualCourse, loadCareer } = useAppStore()
  const [filter, setFilter] = useState<CourseFilter>('all')
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    if (!career) void loadCareer()
  }, [career, loadCareer])

  const courses = useMemo(() => selectCourses({ career, profile, manualCourses }), [career, profile, manualCourses])
  const categories = career?.categories ?? DEFAULT_CATEGORIES
  const isCareer = profile?.mode === 'career'
  const prog = progress(courses, statuses)
  const open = courses.find((c) => c.id === openId) ?? null

  const visible = courses.filter((c) => {
    if (filter === 'active') return statusOf(statuses, c.id) === 'active'
    if (filter === 'pack') return !!packs[c.code]
    return true
  })

  const card = (c: (typeof courses)[number]) => {
    const st = statusOf(statuses, c.id)
    const dimmed = isCareer && curriculumMode === 'realistic' && st !== 'passed' && missingPrereqs(c, statuses).length > 0
    return (
      <CourseCard key={c.id} course={c} color={categoryColor(categories, c.category)} status={st} pack={packs[c.code]} dimmed={dimmed} onOpen={() => setOpenId(c.id)} />
    )
  }

  const btn = (active: boolean) =>
    `rounded-md px-3 py-1.5 text-sm ${active ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900' : 'border border-slate-300 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800'}`

  if (isCareer && !career) return <main className="p-6 text-sm text-slate-500">Cargando malla...</main>

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

      <section className="rounded-lg border border-slate-200 p-4 dark:border-slate-800" aria-label="Progreso global">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
          <span className="text-2xl font-semibold">{prog.pct}% de avance</span>
          <span>Créditos aprobados <b>{prog.creditsPassed} / {prog.credits}</b></span>
          <span>Ramos aprobados <b>{prog.passed} / {prog.total}</b></span>
          {isCareer && <span className="text-xs text-slate-500">(sin contar ramos opcionales)</span>}
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
          <div className="h-full bg-emerald-600 dark:bg-emerald-500" style={{ width: `${prog.pct}%` }} />
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" onClick={() => setFilter(f.id)} className={btn(filter === f.id)}>{f.label}</button>
        ))}
        {isCareer && career && (
          <>
            <span className="mx-1 hidden h-5 w-px bg-slate-300 sm:block dark:bg-slate-700" />
            <div className="inline-flex gap-1" role="group" aria-label="Modo de malla">
              <button type="button" onClick={() => setCurriculumMode('realistic')} className={btn(curriculumMode === 'realistic')}>Modo Carrera (Realista)</button>
              <button type="button" onClick={() => setCurriculumMode('free')} className={btn(curriculumMode === 'free')}>Modo Libre</button>
            </div>
            <label className="ml-auto inline-flex items-center gap-2 text-sm">
              <ListChecks size={16} />
              <span className="hidden sm:inline">Marcar semestres anteriores aprobados</span>
              <select
                value=""
                onChange={(e) => {
                  const n = Number(e.target.value)
                  if (n) approveUpTo(n)
                }}
                className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900"
                aria-label="Marcar semestres anteriores aprobados"
              >
                <option value="">Aprobé hasta...</option>
                {career.semesters.slice(0, -1).map((s) => (
                  <option key={s.number} value={s.number}>Aprobé hasta {s.label}</option>
                ))}
              </select>
            </label>
          </>
        )}
      </div>

      {isCareer && career ? (
        <div className="-mx-4 overflow-x-auto px-4 pb-3 sm:-mx-6 sm:px-6">
          <div className="flex gap-3">
            {career.semesters.map((sem) => {
              const list = visible.filter((c) => c.semester === sem.number)
              return (
                <section key={sem.number} className="flex w-60 shrink-0 flex-col gap-2">
                  <h2 className="text-sm font-semibold text-slate-500">
                    {sem.label} <span className="font-normal">· {sem.courses.reduce((a, c) => a + c.credits, 0)} cr.</span>
                  </h2>
                  {list.map(card)}
                  {list.length === 0 && <p className="rounded-lg border border-dashed border-slate-300 p-3 text-xs text-slate-500 dark:border-slate-700">Sin ramos con este filtro.</p>}
                </section>
              )
            })}
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <ManualForm categories={categories} onAdd={(c) => setOpenId(addManualCourse(c))} />
          {visible.length === 0 ? (
            <p className="text-sm text-slate-500">Aún no hay ramos para mostrar. Agrega uno arriba.</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{visible.map(card)}</div>
          )}
        </div>
      )}

      {open && <CourseModal course={open} allCourses={courses} statuses={statuses} pack={packs[open.code]} onClose={() => setOpenId(null)} />}
    </main>
  )
}

function ManualForm({ categories, onAdd }: { categories: { id: string; label: string }[]; onAdd: (c: { code: string; name: string; credits: number; category: string }) => void }) {
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [credits, setCredits] = useState(3)
  const [category, setCategory] = useState(categories[0].id)
  const f = 'rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900'
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
      <input className={`${f} min-w-48 flex-1`} placeholder="Nombre del ramo" value={name} onChange={(e) => setName(e.target.value)} aria-label="Nombre del ramo" />
      <input className={`${f} w-28`} placeholder="Código" value={code} onChange={(e) => setCode(e.target.value)} aria-label="Código" />
      <input className={`${f} w-20`} type="number" min={0} max={30} value={credits} onChange={(e) => setCredits(Number(e.target.value))} aria-label="Créditos" />
      <select className={f} value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Categoría">
        {categories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
      </select>
      <button type="submit" className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900">
        <Plus size={16} />
        Agregar ramo
      </button>
    </form>
  )
}
