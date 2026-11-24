import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import {
  evaluate as apiEvaluate,
  getTree,
  resetProgress,
  type CooldownMode,
  type CourseTree,
  type EvaluateRequest,
  type EvaluateResponse,
} from '../api/study'

interface StudyState {
  // Preferencia persistida (localStorage.brotal_study_prefs); espeja user_profile.cooldown_mode.
  cooldownMode: CooldownMode
  setCooldownMode: (m: CooldownMode) => void

  tree: CourseTree | null
  status: 'idle' | 'loading' | 'ready' | 'empty'
  selectedNodeId: string | null
  load: (courseId: string) => Promise<void>
  select: (nodeId: string | null) => void
  submit: (nodeId: string, req: Omit<EvaluateRequest, 'cooldown_mode'>) => Promise<EvaluateResponse>
  reset: () => Promise<void>
}

export const useStudyStore = create<StudyState>()(
  persist(
    (set, get) => ({
      cooldownMode: 'semester',
      setCooldownMode: (cooldownMode) => set({ cooldownMode }),

      tree: null,
      status: 'idle',
      selectedNodeId: null,
      load: async (courseId) => {
        set({ status: 'loading', tree: null, selectedNodeId: null })
        const tree = await getTree(courseId)
        if (!tree) {
          set({ status: 'empty' })
          return
        }
        const root = tree.nodes.find((n) => n.parent_ids.length === 0) ?? tree.nodes[0]
        set({ tree, status: 'ready', selectedNodeId: root?.id ?? null })
      },
      select: (selectedNodeId) => set({ selectedNodeId }),
      submit: async (nodeId, req) => {
        const tree = get().tree
        if (!tree) throw new Error('Arbol no cargado')
        const res = await apiEvaluate(tree.course_id, nodeId, { ...req, cooldown_mode: get().cooldownMode })
        set({ tree: { ...tree, progress: { ...tree.progress, [nodeId]: res.progress } } })
        return res
      },
      reset: async () => {
        const tree = get().tree
        if (!tree) return
        await resetProgress(tree.course_id)
        const fresh = await getTree(tree.course_id)
        if (fresh) set({ tree: fresh })
      },
    }),
    { name: 'brotal_study_prefs', partialize: (s) => ({ cooldownMode: s.cooldownMode }) },
  ),
)
