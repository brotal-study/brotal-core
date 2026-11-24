import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { getCareer, installPack, listPacks } from '../api/curriculum'
import type { CareerManifest, Course, CourseStatus, PackSummary } from '../api/types'

export type Theme = 'dark' | 'light'
export type CurriculumMode = 'realistic' | 'free'
export type ProfileMode = 'career' | 'free'
export type CourseFilter = 'all' | 'active' | 'pack'

export interface LocalProfile {
  name: string
  mode: ProfileMode
  careerId: string | null
}

export interface ManualCourse {
  id: string
  code: string
  name: string
  credits: number
  category: string
}

interface AppState {
  // Tema (clave propia: localStorage.brotal_theme)
  theme: Theme
  setTheme: (t: Theme) => void
  toggleTheme: () => void

  // Perfil local persistido (localStorage.brotal_profile)
  profile: LocalProfile | null
  statuses: Record<string, CourseStatus>
  manualCourses: ManualCourse[]
  installedPacks: Record<string, string> // course_code -> version
  curriculumMode: CurriculumMode
  activeCourseId: string | null
  saveProfile: (p: LocalProfile) => void
  setStatus: (courseId: string, s: CourseStatus) => void
  approveUpTo: (semester: number) => void
  setCurriculumMode: (m: CurriculumMode) => void
  setActiveCourse: (id: string | null) => void
  addManualCourse: (c: Omit<ManualCourse, 'id'>) => string
  removeManualCourse: (id: string) => void
  install: (courseCode: string, packId: string) => Promise<void>

  // Datos cargados desde la capa api/ (no persistidos)
  career: CareerManifest | null
  packs: Record<string, PackSummary> // por course_code
  loadCareer: () => Promise<void>
}

const initialTheme = (): Theme =>
  localStorage.getItem('brotal_theme') === 'light' ? 'light' : 'dark'

function applyTheme(t: Theme) {
  localStorage.setItem('brotal_theme', t)
  document.documentElement.classList.toggle('dark', t === 'dark')
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      theme: initialTheme(),
      setTheme: (theme) => {
        applyTheme(theme)
        set({ theme })
      },
      toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),

      profile: null,
      statuses: {},
      manualCourses: [],
      installedPacks: {},
      curriculumMode: 'realistic',
      activeCourseId: null,
      saveProfile: (profile) => {
        const prev = get().profile
        const changedTrack = prev && (prev.mode !== profile.mode || prev.careerId !== profile.careerId)
        set({
          profile,
          ...(changedTrack ? { statuses: {}, activeCourseId: null } : {}),
          career: changedTrack ? null : get().career,
        })
      },
      setStatus: (id, s) => set((st) => ({ statuses: { ...st.statuses, [id]: s } })),
      approveUpTo: (semester) => {
        const career = get().career
        if (!career) return
        const next = { ...get().statuses }
        for (const sem of career.semesters)
          if (sem.number <= semester)
            for (const c of sem.courses) if (!c.optional) next[c.code] = 'passed'
        set({ statuses: next })
      },
      setCurriculumMode: (curriculumMode) => set({ curriculumMode }),
      setActiveCourse: (activeCourseId) => set({ activeCourseId }),
      addManualCourse: (c) => {
        const id = `manual-${Date.now().toString(36)}`
        set((st) => ({ manualCourses: [...st.manualCourses, { ...c, id }] }))
        return id
      },
      removeManualCourse: (id) =>
        set((st) => {
          const { [id]: _drop, ...rest } = st.statuses
          void _drop
          return { manualCourses: st.manualCourses.filter((m) => m.id !== id), statuses: rest }
        }),
      install: async (courseCode, packId) => {
        const res = await installPack(packId)
        set((st) => ({
          installedPacks: { ...st.installedPacks, [courseCode]: res.version },
          statuses: {
            ...st.statuses,
            [courseCode]:
              !st.statuses[courseCode] || st.statuses[courseCode] === 'pending'
                ? 'active'
                : st.statuses[courseCode],
          },
        }))
      },

      career: null,
      packs: {},
      loadCareer: async () => {
        const p = get().profile
        if (!p || p.mode !== 'career' || !p.careerId) {
          set({ career: null, packs: {} })
          return
        }
        const [career, packs] = await Promise.all([getCareer(p.careerId), listPacks(p.careerId)])
        set({ career, packs: Object.fromEntries(packs.map((k) => [k.course_code, k])) })
      },
    }),
    {
      name: 'brotal_profile',
      partialize: (s) => ({
        profile: s.profile,
        statuses: s.statuses,
        manualCourses: s.manualCourses,
        installedPacks: s.installedPacks,
        curriculumMode: s.curriculumMode,
        activeCourseId: s.activeCourseId,
      }),
    },
  ),
)

/** Lista unificada de ramos segun el perfil (malla o manuales). */
export function selectCourses(s: Pick<AppState, 'career' | 'profile' | 'manualCourses'>): Course[] {
  if (s.profile?.mode === 'career' && s.career) {
    return s.career.semesters.flatMap((sem) =>
      sem.courses.map((c) => ({ ...c, id: c.code, semester: sem.number })),
    )
  }
  return s.manualCourses.map((m) => ({
    ...m,
    prerequisites: [],
    semester: null,
    manual: true,
  }))
}

export const DEFAULT_CATEGORIES = [
  { id: 'inf', label: 'Informática', color: '#2E7D5B' },
  { id: 'mat', label: 'Matemáticas y Ciencias', color: '#2B5B84' },
  { id: 'eng', label: 'Inglés', color: '#8C6D1F' },
  { id: 'gen', label: 'Formación Fundamental', color: '#8A335C' },
]

export const STATUS_LABEL: Record<CourseStatus, string> = {
  pending: 'Pendiente',
  active: 'Cursando',
  passed: 'Aprobado',
  archived: 'Archivado',
}
