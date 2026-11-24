import { useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Network } from 'lucide-react'
import { selectCourses, useAppStore } from '../store/useAppStore'

// Placeholder del Issue #7 (SkillTree con React Flow).
export default function CourseStudyPage() {
  const { courseId = '' } = useParams()
  const { career, profile, manualCourses, loadCareer, setActiveCourse } = useAppStore()
  const id = decodeURIComponent(courseId)

  useEffect(() => {
    if (!career) void loadCareer()
  }, [career, loadCareer])
  useEffect(() => setActiveCourse(id), [id, setActiveCourse])

  const course = selectCourses({ career, profile, manualCourses }).find((c) => c.id === id)

  return (
    <main className="mx-auto flex max-w-xl flex-col items-center gap-3 px-4 py-20 text-center">
      <Network size={32} className="text-slate-400" />
      <h1 className="text-xl font-semibold">{course ? course.name : 'Ramo no encontrado'}</h1>
      {course && <p className="font-mono text-xs text-slate-500">{course.code}</p>}
      <p className="text-sm text-slate-500">El Árbol de Estudio estará disponible próximamente (Issue #7).</p>
      <Link to="/" className="text-sm underline">Volver a Mi Malla</Link>
    </main>
  )
}
