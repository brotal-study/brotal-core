import { useMemo } from 'react'
import { Background, Controls, MarkerType, Panel, ReactFlow, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { FlaskConical, Sprout } from 'lucide-react'
import type { CourseTree, PackNode } from '../../api/study'
import { useAppStore } from '../../store/useAppStore'
import SkillNode, { type SkillFlowNode } from './SkillNode'

const nodeTypes = { skill: SkillNode }
const W = 280
const GAP_Y = 200

/** Profundidad dentro de cada rama (evita huecos cuando un nodo practice cuelga de uno theory). */
function branchDepths(nodes: PackNode[]): Record<string, number> {
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const memo: Record<string, number> = {}
  const d = (id: string, seen: Set<string> = new Set()): number => {
    if (memo[id] !== undefined) return memo[id]
    if (seen.has(id)) return 0
    seen.add(id)
    const cur = byId[id]
    const sameBranchParents = (cur?.parent_ids ?? []).filter((p) => byId[p]?.branch === cur.branch)
    return (memo[id] = sameBranchParents.length ? 1 + Math.max(...sameBranchParents.map((p) => d(p, seen))) : 0)
  }
  nodes.forEach((n) => d(n.id))
  return memo
}

/**
 * Layout bi-direccional: la copa (theory) crece hacia arriba desde y=0;
 * las raices (practice) crecen hacia abajo desde y=+GAP_Y. Cada fila se centra horizontalmente.
 */
function layout(nodes: PackNode[]): Record<string, { x: number; y: number }> {
  const dep = branchDepths(nodes)
  const rows = new Map<string, PackNode[]>()
  for (const n of nodes) {
    const key = `${n.branch}:${dep[n.id]}`
    rows.set(key, [...(rows.get(key) ?? []), n])
  }
  const pos: Record<string, { x: number; y: number }> = {}
  for (const [key, row] of rows) {
    const [branch, depth] = key.split(':')
    const y = branch === 'theory' ? -Number(depth) * GAP_Y : (Number(depth) + 1) * GAP_Y
    row.forEach((n, i) => (pos[n.id] = { x: (i - (row.length - 1) / 2) * W, y }))
  }
  return pos
}

interface Props {
  tree: CourseTree
  selectedId: string | null
  now: number
  onSelect: (id: string) => void
}

export default function SkillTree({ tree, selectedId, now, onSelect }: Props) {
  const theme = useAppStore((s) => s.theme)
  const pos = useMemo(() => layout(tree.nodes), [tree.nodes])
  const hasPractice = tree.nodes.some((n) => n.branch === 'practice')

  const nodes: SkillFlowNode[] = tree.nodes.map((n) => ({
    id: n.id,
    type: 'skill',
    position: pos[n.id],
    data: { node: n, progress: tree.progress[n.id], selected: n.id === selectedId, now },
    draggable: false,
  }))

  const byId = Object.fromEntries(tree.nodes.map((n) => [n.id, n]))
  const edges: Edge[] = tree.nodes.flatMap((n) =>
    n.parent_ids
      .filter((p) => byId[p])
      .map((p) => {
        // Copa: del tope del padre a la base del hijo (crece hacia arriba). Raices: hacia abajo.
        const up = n.branch === 'theory'
        const mastered = tree.progress[p]?.mastery_level === 3
        const stroke = mastered ? '#10b981' : '#94a3b8'
        return {
          id: `${p}->${n.id}`,
          source: p,
          target: n.id,
          sourceHandle: up ? 'top-s' : 'bottom-s',
          targetHandle: up ? 'bottom-t' : 'top-t',
          animated: !mastered,
          markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 16, height: 16 },
          style: { strokeWidth: 2, stroke },
        }
      }),
  )

  return (
    <ReactFlow
      key={tree.course_id}
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      forceColorMode={theme}
      fitView
      fitViewOptions={{ padding: 0.25 }}
      minZoom={0.3}
      maxZoom={1.6}
      nodesConnectable={false}
      onNodeClick={(_, n) => onSelect(n.id)}
      proOptions={{ hideAttribution: true }}
    >
      <Background />
      <Controls showInteractive={false} />
      <Panel position="top-left" className="flex items-center gap-3 rounded-md border border-slate-200 bg-white/90 px-2.5 py-1.5 text-[11px] text-slate-600 shadow-sm backdrop-blur dark:border-slate-700 dark:bg-slate-900/90 dark:text-slate-300">
        <span className="inline-flex items-center gap-1">
          <Sprout size={13} className="text-emerald-600 dark:text-emerald-400" /> Copa · Teoría
        </span>
        <span className={`inline-flex items-center gap-1 ${hasPractice ? '' : 'opacity-50'}`} title={hasPractice ? undefined : 'Este pack demo solo incluye nodos de teoría'}>
          <FlaskConical size={13} className="text-amber-600 dark:text-amber-400" /> Raíces · Práctica
        </span>
      </Panel>
    </ReactFlow>
  )
}
