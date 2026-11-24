import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import { Clock, Dumbbell, FlaskConical, Sprout, Trophy } from 'lucide-react'
import { inCooldown, type NodeProgress, type PackNode } from '../../api/study'
import { formatRemaining, LEVEL_STYLE } from './studyUtils'

export type SkillNodeData = {
  node: PackNode
  progress: NodeProgress
  selected: boolean
  now: number
}
export type SkillFlowNode = Node<SkillNodeData, 'skill'>

export default function SkillNode({ data }: NodeProps<SkillFlowNode>) {
  const { node, progress, selected, now } = data
  const lvl = LEVEL_STYLE[progress.mastery_level] ?? LEVEL_STYLE[0]
  const cooling = inCooldown(progress, now)
  const remaining = cooling ? new Date(progress.next_review_at!).getTime() - now : 0
  const isPractice = node.branch === 'practice'

  return (
    <div
      className={`w-64 rounded-lg border border-l-4 bg-white p-3 text-left shadow-sm transition hover:shadow-md dark:bg-slate-900 ${
        lvl.accent
      } ${
        selected
          ? 'border-slate-900 ring-2 ring-slate-900/30 dark:border-slate-100 dark:ring-slate-100/30'
          : 'border-slate-300 dark:border-slate-700'
      }`}
    >
      {/* Handles superior/inferior para unir la copa (theory) y las raices (practice). */}
      <Handle id="top-t" type="target" position={Position.Top} className="!h-2 !w-2 !border-0 !bg-slate-400 dark:!bg-slate-500" />
      <Handle id="top-s" type="source" position={Position.Top} className="!h-2 !w-2 !border-0 !bg-slate-400 dark:!bg-slate-500" />
      <Handle id="bottom-t" type="target" position={Position.Bottom} className="!h-2 !w-2 !border-0 !bg-slate-400 dark:!bg-slate-500" />
      <Handle id="bottom-s" type="source" position={Position.Bottom} className="!h-2 !w-2 !border-0 !bg-slate-400 dark:!bg-slate-500" />

      <div className="flex items-center justify-between gap-2 text-[10px] text-slate-500 dark:text-slate-400">
        <span className="inline-flex min-w-0 items-center gap-1 truncate">
          {isPractice ? <FlaskConical size={11} className="shrink-0 text-amber-600 dark:text-amber-400" /> : <Sprout size={11} className="shrink-0 text-emerald-600 dark:text-emerald-400" />}
          <span className="truncate">{node.block}</span>
        </span>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${lvl.pill}`}>
          {progress.mastery_level}/3
        </span>
      </div>
      <div className="mt-1 text-sm font-semibold leading-snug">{node.title}</div>

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
        <span className="inline-flex items-center gap-1" title="Reps de practica (no suben el nivel)">
          <Dumbbell size={12} /> Reps {progress.training_reps}
        </span>
        <span className="inline-flex items-center gap-1" title="Mejor nota">
          <Trophy size={12} /> Mejor nota {progress.best_score > 0 ? progress.best_score.toFixed(1) : '-'}
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
