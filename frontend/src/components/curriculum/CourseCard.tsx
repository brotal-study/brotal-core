import {
  Archive,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  CircleDashed,
  Package,
} from 'lucide-react'
import type { CourseProgressSummary } from '../../api/curriculum'
import type { Course, CourseStatus, PackSummary } from '../../api/types'
import { STATUS_LABEL } from '../../store/useAppStore'

const STATUS_ICON = {
  pending: CircleDashed,
  active: BookOpen,
  passed: CheckCircle2,
  archived: Archive,
} as const

interface Props {
  course: Course
  color: string
  status: CourseStatus
  pack?: PackSummary
  progressSummary?: CourseProgressSummary
  hasContent?: boolean
  dimmed: boolean
  quickApproveMode?: boolean
  onOpen: () => void
  onStudy?: () => void
}

export default function CourseCard({
  course,
  color,
  status,
  pack,
  progressSummary,
  hasContent = false,
  dimmed,
  quickApproveMode = false,
  onOpen,
  onStudy,
}: Props) {
  const Icon = STATUS_ICON[status]
  const showStudyBtn = (status === 'active' || hasContent) && !quickApproveMode && !!onStudy
  const showActiveProgress =
    status === 'active' && !!progressSummary && progressSummary.total > 0
  const masteredPct = showActiveProgress
    ? Math.round((progressSummary.mastered / progressSummary.total) * 100)
    : 0
  const startedPct = showActiveProgress
    ? Math.round((progressSummary.started / progressSummary.total) * 100)
    : 0
  const barPct = Math.max(masteredPct, Math.min(100, Math.round(startedPct * 0.45 + masteredPct * 0.55)))

  const cardStyleByStatus =
    status === 'passed'
      ? 'border-emerald-400 border-l-emerald-600 bg-emerald-50/75 text-slate-900 dark:border-emerald-700/80 dark:border-l-emerald-400 dark:bg-emerald-950/35 dark:text-slate-100'
      : status === 'active'
        ? 'border-indigo-500 border-l-indigo-600 bg-indigo-50/80 text-slate-900 ring-1 ring-indigo-500/25 dark:border-indigo-500/80 dark:border-l-indigo-400 dark:bg-indigo-950/45 dark:text-slate-100'
        : 'border-slate-200 border-l-slate-400 bg-white text-slate-800 dark:border-slate-800 dark:border-l-slate-600 dark:bg-slate-900/70 dark:text-slate-200'

  const badgeStyleByStatus =
    status === 'passed'
      ? 'bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950'
      : status === 'active'
        ? 'bg-indigo-600 text-white dark:bg-indigo-500 dark:text-white'
        : 'bg-slate-200/80 text-slate-700 dark:bg-slate-800 dark:text-slate-300'

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen()
        }
      }}
      className={`group flex w-full cursor-pointer flex-col gap-1.5 rounded-lg border border-l-4 p-3 text-left transition hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${cardStyleByStatus} ${
        dimmed ? 'opacity-45 hover:opacity-95' : ''
      } ${quickApproveMode ? 'hover:ring-2 hover:ring-emerald-500/60' : ''}`}
    >
      <div className="flex items-center justify-between text-[11px] font-medium text-slate-600 dark:text-slate-300">
        <span className="inline-flex items-center gap-1.5 font-mono">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: color }}
            aria-hidden="true"
          />
          {course.code}
        </span>
        <span>{course.credits} cr.</span>
      </div>
      <div className="text-sm font-semibold leading-snug">
        {course.name}
        {course.optional && (
          <span className="ml-1 text-[11px] font-normal text-slate-500">(opcional)</span>
        )}
      </div>
      {showActiveProgress && progressSummary && (
        <div className="flex flex-col gap-1 pt-0.5">
          <div className="truncate text-[10px] font-medium text-indigo-900/80 dark:text-indigo-200/80">
            {progressSummary.started}/{progressSummary.total} iniciados · {progressSummary.mastered}/
            {progressSummary.total} en 3/3
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-indigo-200/80 dark:bg-indigo-900/70">
            <div
              className="h-full bg-indigo-600 transition-all dark:bg-indigo-400"
              style={{ width: `${barPct}%` }}
            />
          </div>
        </div>
      )}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-1.5 pt-1.5 text-[11px]">
        <div className="flex flex-wrap items-center gap-1.5">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold ${badgeStyleByStatus}`}
          >
            <Icon size={12} />
            {STATUS_LABEL[status]}
          </span>
          {pack && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-slate-400/50 px-2 py-0.5 text-slate-600 dark:text-slate-300"
              title={pack.title}
            >
              <Package size={12} />
              Pack
            </span>
          )}
        </div>

        {showStudyBtn && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onStudy()
            }}
            className="inline-flex items-center gap-1 rounded-md bg-indigo-600 px-2 py-0.5 text-[11px] font-semibold text-white shadow-xs hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400"
          >
            Estudiar <ArrowRight size={11} />
          </button>
        )}
      </div>
    </div>
  )
}
