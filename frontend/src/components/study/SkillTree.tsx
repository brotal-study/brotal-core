import { useEffect, useMemo, useRef } from 'react'
import {
  Background,
  Controls,
  MarkerType,
  Panel,
  ReactFlow,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { FlaskConical, LocateFixed, Sprout } from 'lucide-react'
import type { CourseTree, PackNode } from '../../api/study'
import { useAppStore } from '../../store/useAppStore'
import SkillNode, { CourseRootNode, type CourseRootFlowNode, type SkillFlowNode } from './SkillNode'

export type TreeBranchFilter = 'all' | 'theory' | 'practice'

const ROOT_ID = '__course_root__'
const nodeTypes = { skill: SkillNode, courseRoot: CourseRootNode }
const W = 296
const GAP_Y = 195

/** Profundidad topológica dentro de cada rama (theory hacia arriba, practice hacia abajo). */
function branchDepths(nodes: PackNode[]): Record<string, number> {
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const memo: Record<string, number> = {}
  const d = (id: string, seen: Set<string> = new Set()): number => {
    if (memo[id] !== undefined) return memo[id]
    if (seen.has(id)) return 0
    seen.add(id)
    const cur = byId[id]
    const sameBranchParents = (cur?.parent_ids ?? []).filter((p) => byId[p]?.branch === cur.branch)
    return (memo[id] = sameBranchParents.length
      ? 1 + Math.max(...sameBranchParents.map((p) => d(p, new Set(seen))))
      : 0)
  }
  nodes.forEach((n) => d(n.id))
  return memo
}

/** Calcula todos los ancestros recursivos (`parent_ids`) de un nodo seleccionado. */
function collectAncestors(nodes: PackNode[], targetId: string | null): Set<string> {
  const out = new Set<string>()
  if (!targetId) return out
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const stack = [targetId]
  while (stack.length > 0) {
    const curId = stack.pop()!
    if (out.has(curId)) continue
    out.add(curId)
    const node = byId[curId]
    if (node) {
      for (const pid of node.parent_ids) {
        if (byId[pid] && !out.has(pid)) {
          stack.push(pid)
        }
      }
    }
  }
  return out
}

/**
 * Layout ordenado por niveles con heurística de baricentro para minimizar cruces:
 * - Nodo raíz central en (0, 0)
 * - Copa (theory) crece hacia arriba: y = -(depth + 1) * GAP_Y
 * - Raíces (practice) crecen hacia abajo: y = +(depth + 1) * GAP_Y
 */
function layout(nodes: PackNode[]): Record<string, { x: number; y: number }> {
  const dep = branchDepths(nodes)
  const pos: Record<string, { x: number; y: number }> = {
    [ROOT_ID]: { x: -16, y: 0 },
  }

  for (const branch of ['theory', 'practice'] as const) {
    const branchNodes = nodes.filter((n) => n.branch === branch)
    const maxDepth = branchNodes.reduce((m, n) => Math.max(m, dep[n.id] ?? 0), 0)

    for (let depth = 0; depth <= maxDepth; depth++) {
      const row = branchNodes.filter((n) => (dep[n.id] ?? 0) === depth)
      if (row.length === 0) continue

      row.sort((a, b) => {
        const parentsA = a.parent_ids.filter((p) => pos[p] !== undefined)
        const parentsB = b.parent_ids.filter((p) => pos[p] !== undefined)
        const baryA =
          parentsA.length > 0
            ? parentsA.reduce((sum, p) => sum + pos[p].x, 0) / parentsA.length
            : 0
        const baryB =
          parentsB.length > 0
            ? parentsB.reduce((sum, p) => sum + pos[p].x, 0) / parentsB.length
            : 0
        if (Math.abs(baryA - baryB) > 1) return baryA - baryB
        const blockCmp = a.block.localeCompare(b.block)
        return blockCmp !== 0 ? blockCmp : a.id.localeCompare(b.id)
      })

      const y = branch === 'theory' ? -(depth + 1) * GAP_Y : (depth + 1) * GAP_Y
      row.forEach((n, i) => {
        pos[n.id] = { x: (i - (row.length - 1) / 2) * W, y }
      })
    }
  }

  return pos
}

interface Props {
  tree: CourseTree
  selectedId: string | null
  branchFilter?: TreeBranchFilter
  now: number
  onSelect: (id: string) => void
}

export default function SkillTree({
  tree,
  selectedId,
  branchFilter = 'all',
  now,
  onSelect,
}: Props) {
  const theme = useAppStore((s) => s.theme)
  const rfRef = useRef<ReactFlowInstance<Node, Edge> | null>(null)

  const visibleSkillNodes = useMemo(
    () =>
      tree.nodes.filter((n) =>
        branchFilter === 'all' ? true : n.branch === branchFilter,
      ),
    [tree.nodes, branchFilter],
  )

  const pos = useMemo(() => layout(visibleSkillNodes), [visibleSkillNodes])
  const dep = useMemo(() => branchDepths(visibleSkillNodes), [visibleSkillNodes])
  const pathSet = useMemo(() => collectAncestors(tree.nodes, selectedId), [tree.nodes, selectedId])
  const hasSelection = Boolean(selectedId && pathSet.size > 0)
  const hasPractice = tree.nodes.some((n) => n.branch === 'practice')

  const masteredCount = useMemo(
    () => Object.values(tree.progress).filter((p) => p.mastery_level === 3).length,
    [tree.progress],
  )

  const rootNode: CourseRootFlowNode = {
    id: ROOT_ID,
    type: 'courseRoot',
    position: pos[ROOT_ID] ?? { x: -16, y: 0 },
    data: {
      code: tree.course_code,
      title: tree.title,
      worldMetaphor: tree.world_metaphor,
      mastered: masteredCount,
      total: tree.nodes.length,
    },
    draggable: false,
    selectable: false,
  }

  const skillNodes: SkillFlowNode[] = visibleSkillNodes.map((n) => {
    const inPath = pathSet.has(n.id)
    return {
      id: n.id,
      type: 'skill',
      position: pos[n.id] ?? { x: 0, y: 0 },
      data: {
        node: n,
        progress: tree.progress[n.id],
        selected: n.id === selectedId,
        inPath,
        dimmed: hasSelection && !inPath,
        now,
      },
      draggable: false,
    }
  })

  const nodes: Node[] = [rootNode, ...skillNodes]

  const byId = Object.fromEntries(visibleSkillNodes.map((n) => [n.id, n]))
  const edges: Edge[] = []

  for (const n of visibleSkillNodes) {
    const up = n.branch === 'theory'
    const sameBranchParents = n.parent_ids.filter(
      (p) => byId[p] && byId[p].branch === n.branch,
    )

    if ((dep[n.id] ?? 0) === 0 || sameBranchParents.length === 0) {
      const inPath = pathSet.has(n.id)
      const stroke = inPath ? '#6366f1' : up ? '#10b981' : '#f59e0b'
      edges.push({
        id: `${ROOT_ID}->${n.id}`,
        source: ROOT_ID,
        target: n.id,
        sourceHandle: up ? 'top-s' : 'bottom-s',
        targetHandle: up ? 'bottom-t' : 'top-t',
        animated: inPath,
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 15, height: 15 },
        style: {
          strokeWidth: inPath ? 2.5 : 1.75,
          stroke,
          opacity: hasSelection && !inPath ? 0.25 : 0.85,
        },
      })
    }

    for (const p of sameBranchParents) {
      const edgeInPath = pathSet.has(n.id) && pathSet.has(p)
      const mastered = tree.progress[p]?.mastery_level === 3
      const stroke = edgeInPath ? '#6366f1' : mastered ? '#10b981' : '#94a3b8'
      edges.push({
        id: `${p}->${n.id}`,
        source: p,
        target: n.id,
        sourceHandle: up ? 'top-s' : 'bottom-s',
        targetHandle: up ? 'bottom-t' : 'top-t',
        animated: edgeInPath || !mastered,
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 16, height: 16 },
        style: {
          strokeWidth: edgeInPath ? 2.8 : 2,
          stroke,
          opacity: hasSelection && !edgeInPath ? 0.25 : 1,
        },
      })
    }
  }

  const translateExtent = useMemo<[[number, number], [number, number]]>(() => {
    const coords = Object.values(pos)
    if (coords.length === 0) return [[-1000, -1000], [1000, 1000]]
    const xs = coords.map((c) => c.x)
    const ys = coords.map((c) => c.y)
    const minX = Math.min(...xs) - 380
    const maxX = Math.max(...xs) + 660
    const minY = Math.min(...ys) - 360
    const maxY = Math.max(...ys) + 480
    return [
      [minX, minY],
      [maxX, maxY],
    ]
  }, [pos])

  useEffect(() => {
    const timer = setTimeout(() => {
      rfRef.current?.fitView({ padding: 0.22, duration: 250 })
    }, 40)
    return () => clearTimeout(timer)
  }, [branchFilter, tree.course_id, tree.nodes.length])

  const centerTree = () => {
    rfRef.current?.fitView({ padding: 0.22, duration: 300 })
  }

  return (
    <ReactFlow
      key={tree.course_id}
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      forceColorMode={theme}
      onInit={(instance) => {
        rfRef.current = instance
      }}
      fitView
      fitViewOptions={{ padding: 0.22 }}
      minZoom={0.35}
      maxZoom={1.5}
      translateExtent={translateExtent}
      nodesConnectable={false}
      onNodeClick={(_, n) => {
        if (n.id !== ROOT_ID) onSelect(n.id)
      }}
      proOptions={{ hideAttribution: true }}
    >
      <Background />
      <Controls showInteractive={false} />
      <Panel
        position="top-left"
        className="flex flex-wrap items-center gap-2.5 rounded-md border border-slate-200 bg-white/95 px-2.5 py-1.5 text-[11px] text-slate-600 shadow-sm backdrop-blur dark:border-slate-700 dark:bg-slate-900/95 dark:text-slate-300"
      >
        <span className="inline-flex items-center gap-1 font-medium">
          <Sprout size={13} className="text-emerald-600 dark:text-emerald-400" /> Copa · Teoría
        </span>
        <span
          className={`inline-flex items-center gap-1 font-medium ${hasPractice ? '' : 'opacity-50'}`}
          title={hasPractice ? undefined : 'Este ramo aún no tiene nodos de práctica'}
        >
          <FlaskConical size={13} className="text-amber-600 dark:text-amber-400" /> Raíces · Práctica
        </span>
        <span className="h-3.5 w-px bg-slate-300 dark:bg-slate-700" />
        <button
          type="button"
          onClick={centerTree}
          className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
        >
          <LocateFixed size={12} />
          Centrar árbol
        </button>
      </Panel>
    </ReactFlow>
  )
}
