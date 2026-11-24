import { BookOpenCheck, CircleDashed, Archive, Loader, Package } from 'lucide-react'
import type { Course, CourseStatus, PackSummary } from '../../api/types'
import { STATUS_LABEL } from '../../store/useAppStore'

const STATUS_ICON = {
  pending: CircleDashed,
  active: Loader,
  passed: BookOpenCheck,
  archived: Archive,
} as const

interface Props {
  course: Course
  color: string
  status: CourseStatus
  pack?: PackSummary
  dimmed: boolean
  onOpen: () => void
}

export default function CourseCard({ course, color, status, pack, dimmed, onOpen }: Props) {
  const Icon = STATUS_ICON[status]
  return (
    <button
      type="button"
      onClick={onOpen}
      style={{
        borderColor: `color-mix(in srgb, ${color} 55%, transparent)`,
        backgroundColor: `color-mix(in srgb, ${color} ${status === 'passed' ? 24 : 12}%, transparent)`,
        borderLeftColor: color,
      }}
      className={`flex w-full flex-col gap-1.5 rounded-lg border border-l-4 p-3 text-left transition hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 ${
        dimmed ? 'opacity-40 hover:opacity-90' : ''
      } ${status === 'archived' ? 'grayscale' : ''}`}
    >
      <div className="flex items-center justify-between text-[11px] font-medium text-slate-600 dark:text-slate-300">
        <span className="font-mono">{course.code}</span>
        <span>{course.credits} cr.</span>
      </div>
      <div className="text-sm font-semibold leading-snug">
        {course.name}
        {course.optional && <span className="ml-1 text-[11px] font-normal text-slate-500">(opcional)</span>}
      </div>
      <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-1 text-[11px]">
        <span className="inline-flex items-center gap-1 rounded-full bg-white/70 px-2 py-0.5 font-medium dark:bg-slate-900/60">
          <Icon size={12} />
          {STATUS_LABEL[status]}
        </span>
        {pack && (
          <span
            className="inline-flex items-center gap-1 rounded-full border border-slate-400/50 px-2 py-0.5 text-slate-600 dark:text-slate-300"
            title={pack.title}
          >
            <Package size={12} />
            Pack · Creado {pack.metadata.created_year} · Act. {pack.metadata.updated_year}
          </span>
        )}
      </div>
    </button>
  )
}
