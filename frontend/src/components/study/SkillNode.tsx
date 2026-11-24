import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import { Clock, Compass, Dumbbell, FlaskConical, Sprout, Trophy } from 'lucide-react'
import { inCooldown, type NodeProgress, type PackNode } from '../../api/study'
import { formatRemaining, LEVEL_STYLE } from './studyUtils'

export type SkillNodeData = {
  node: PackNode
  progress: NodeProgress
  selected: boolean
  inPath?: boolean
  dimmed?: boolean
  now: number
}
export type SkillFlowNode = Node<SkillNodeData, 'skill'>

export type CourseRootNodeData = {
  code: string
  title: string
  worldMetaphor: string | null
  mastered: number
  total: number
}
export type CourseRootFlowNode = Node<CourseRootNodeData, 'courseRoot'>

export function CourseRootNode({ data }: NodeProps<CourseRootFlowNode>) {
  return (
    <div className="w-72 cursor-default rounded-xl border-2 border-indigo-500 bg-indigo-950 px-4 py-3 text-center text-white shadow-md dark:border-indigo-400 dark:bg-slate-900">
      <Handle
        id="top-s"
        type="source"
        position={Position.Top}
        className="!h-2.5 !w-2.5 !border-0 !bg-emerald-400"
      />
      <Handle
        id="bottom-s"
        type="source"
        position={Position.Bottom}
        className="!h-2.5 !w-2.5 !border-0 !bg-amber-400"
      />
      <div className="inline-flex items-center gap-1.5 rounded-full bg-indigo-500/30 px-2.5 py-0.5 font-mono text-[11px] font-semibold text-indigo-200">
        <Compass size={12} />
        Núcleo del Ramo · {data.code}
      </div>
      <div className="mt-1 text-sm font-bold leading-snug">{data.title}</div>
      {data.worldMetaphor && (
        <div className="mt-0.5 truncate text-[11px] text-indigo-200/80">{data.worldMetaphor}</div>
      )}
      <div className="mt-1.5 flex items-center justify-center gap-3 border-t border-indigo-800/80 pt-1.5 text-[10px] text-indigo-200">
        <span className="inline-flex items-center gap-1">
          <Sprout size={11} className="text-emerald-400" /> Copa: Teoría
        </span>
        <span>·</span>
        <span className="inline-flex items-center gap-1">
          <FlaskConical size={11} className="text-amber-400" /> Raíces: Práctica ({data.mastered}/{data.total} dom.)
        </span>
      </div>
    </div>
  )
}

export default function SkillNode({ data }: NodeProps<SkillFlowNode>) {
  const { node, progress, selected, inPath = false, dimmed = false, now } = data
  const lvl = LEVEL_STYLE[progress.mastery_level] ?? LEVEL_STYLE[0]
  const cooling = inCooldown(progress, now)
  const remaining = cooling ? new Date(progress.next_review_at!).getTime() - now : 0
  const isPractice = node.branch === 'practice'

  const baseTone = isPractice
    ? 'border-l-amber-500 bg-amber-50/40 dark:border-l-amber-400 dark:bg-amber-950/20'
    : `${lvl.accent} bg-white dark:bg-slate-900`

  const selectionTone = selected
    ? isPractice
      ? 'border-amber-600 ring-2 ring-amber-500/50 dark:border-amber-400 dark:ring-amber-400/40'
      : 'border-indigo-600 ring-2 ring-indigo-500/40 dark:border-indigo-300 dark:ring-indigo-400/40'
    : inPath
      ? 'border-indigo-500 ring-2 ring-indigo-400/35 dark:border-indigo-400 dark:ring-indigo-400/30'
      : isPractice
        ? 'border-amber-300/90 dark:border-amber-700/80'
        : 'border-slate-300 dark:border-slate-700'

  return (
    <div
      className={`w-64 rounded-lg border border-l-4 p-3 text-left shadow-sm transition hover:shadow-md ${baseTone} ${selectionTone} ${
        dimmed ? 'opacity-40 hover:opacity-90' : ''
      }`}
    >
      <Handle
        id="top-t"
        type="target"
        position={Position.Top}
        className="!h-2 !w-2 !border-0 !bg-slate-400 dark:!bg-slate-500"
      />
      <Handle
        id="top-s"
        type="source"
        position={Position.Top}
        className="!h-2 !w-2 !border-0 !bg-slate-400 dark:!bg-slate-500"
      />
      <Handle
        id="bottom-t"
        type="target"
        position={Position.Bottom}
        className="!h-2 !w-2 !border-0 !bg-slate-400 dark:!bg-slate-500"
      />
      <Handle
        id="bottom-s"
        type="source"
        position={Position.Bottom}
        className="!h-2 !w-2 !border-0 !bg-slate-400 dark:!bg-slate-500"
      />

      <div className="flex items-center justify-between gap-2 text-[10px] text-slate-500 dark:text-slate-400">
        <span className="inline-flex min-w-0 items-center gap-1 truncate">
          {isPractice ? (
            <FlaskConical size={11} className="shrink-0 text-amber-600 dark:text-amber-400" />
          ) : (
            <Sprout size={11} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
          )}
          <span className="truncate">{node.block}</span>
        </span>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${lvl.pill}`}>
          {progress.mastery_level}/3
        </span>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-1">
        {isPractice && (
          <span className="inline-flex items-center gap-1 rounded border border-amber-300 bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-900 dark:border-amber-700 dark:bg-amber-900/60 dark:text-amber-200">
            Examen / Práctica
          </span>
        )}
        {inPath && !selected && (
          <span className="inline-flex items-center rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-800 dark:bg-indigo-900/60 dark:text-indigo-200">
            Prerrequisito
          </span>
        )}
      </div>

      <div className="mt-1 break-words text-sm font-semibold leading-snug">{node.title}</div>

      <div className="mt-2 flex gap-1" aria-label={`Nivel ${progress.mastery_level} de 3`}>
        {[1, 2, 3].map((i) => (
          <span
            key={i}
            className={`h-1.5 flex-1 rounded-full ${
              i <= progress.mastery_level ? lvl.bar : 'bg-slate-200 dark:bg-slate-700'
            }`}
          />
        ))}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-600 dark:text-slate-300">
        <span
          className="inline-flex items-center gap-1"
          title="Reps de práctica (no suben el nivel)"
        >
          <Dumbbell size={12} /> Reps {progress.training_reps}
        </span>
        <span className="inline-flex items-center gap-1" title="Mejor nota">
          <Trophy size={12} /> Mejor nota{' '}
          {progress.best_score > 0 ? progress.best_score.toFixed(1) : '-'}
        </span>
      </div>
      {cooling && (
        <div className="mt-1.5 inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-900/50 dark:text-amber-200">
          <Clock size={12} /> En cooldown · {formatRemaining(remaining)}
        </div>
      )}
    </div>
  )
}
