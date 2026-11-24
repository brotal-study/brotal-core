import { create } from 'zustand'
import {
  bulkApproveCareer,
  createManualCourse,
  deleteCourse,
  getCareer,
  getProfile,
  installPack,
  listPacks,
  listUserCourses,
  patchCourseStatus,
  patchProfile,
} from '../api/curriculum'
import type { CareerManifest, Course, CourseStatus, PackSummary } from '../api/types'
import { useStudyStore } from './useStudyStore'

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
  // Inicializacion desde FastAPI
  hydrated: boolean
  hydrate: () => Promise<void>

  // Tema (localStorage.brotal_theme + sincronizado en SQLite user_profile.theme)
  theme: Theme
  setTheme: (t: Theme) => void
  toggleTheme: () => void

  // Perfil y estado de malla/ramos persistidos en SQLite via FastAPI
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

  // Datos de malla y packs disponibles
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

export const useAppStore = create<AppState>()((set, get) => ({
  hydrated: false,
  hydrate: async () => {
    try {
      const [apiProf, userCourses] = await Promise.all([getProfile(), listUserCourses()])
      applyTheme(apiProf.theme)
      useStudyStore.setState({ cooldownMode: apiProf.cooldown_mode })

      const manualCourses: ManualCourse[] = []
      const statuses: Record<string, CourseStatus> = {}
      const installedPacks: Record<string, string> = {}

      for (const c of userCourses) {
        if (c.manual) {
          manualCourses.push({
            id: c.id,
            code: c.code,
            name: c.name,
            credits: c.credits,
            category: c.category,
          })
          statuses[c.id] = c.status
        } else {
          const key = c.course_code ?? c.id
          statuses[key] = c.status
          if (c.source_type === 'pack' && c.pack_version) {
            installedPacks[key] = c.pack_version
          }
        }
      }

      const hasConfiguredProfile =
        apiProf.career_id !== null ||
        apiProf.curriculum_mode === 'free' ||
        apiProf.display_name !== 'Estudiante' ||
        userCourses.length > 0

      const profile: LocalProfile | null = hasConfiguredProfile
        ? {
            name: apiProf.display_name,
            mode: apiProf.career_id ? 'career' : 'free',
            careerId: apiProf.career_id,
          }
        : null

      set({
        hydrated: true,
        theme: apiProf.theme,
        profile,
        curriculumMode: apiProf.curriculum_mode,
        manualCourses,
        statuses,
        installedPacks,
      })

      if (profile?.mode === 'career' && profile.careerId) {
        await get().loadCareer()
      }
    } catch {
      set({ hydrated: true })
    }
  },

  theme: initialTheme(),
  setTheme: (theme) => {
    applyTheme(theme)
    set({ theme })
    void patchProfile({ theme }).catch(() => undefined)
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
    const nextCurriculumMode: CurriculumMode =
      profile.mode === 'free' ? 'free' : get().curriculumMode
    set({
      profile,
      curriculumMode: nextCurriculumMode,
      ...(changedTrack ? { statuses: {}, activeCourseId: null } : {}),
      career: changedTrack ? null : get().career,
    })
    void patchProfile({
      display_name: profile.name,
      career_id: profile.mode === 'career' ? profile.careerId : null,
      curriculum_mode: nextCurriculumMode,
    }).catch(() => undefined)
  },
  setStatus: (id, s) => {
    set((st) => ({ statuses: { ...st.statuses, [id]: s } }))
    void patchCourseStatus(id, s).catch(() => undefined)
  },
  approveUpTo: (semester) => {
    const career = get().career
    if (!career) return
    const next = { ...get().statuses }
    for (const sem of career.semesters)
      if (sem.number <= semester)
        for (const c of sem.courses) if (!c.optional) next[c.code] = 'passed'
    set({ statuses: next })
    void bulkApproveCareer(career.id, semester, 'passed').catch(() => undefined)
  },
  setCurriculumMode: (curriculumMode) => {
    set({ curriculumMode })
    void patchProfile({ curriculum_mode: curriculumMode }).catch(() => undefined)
  },
  setActiveCourse: (activeCourseId) => set({ activeCourseId }),
  addManualCourse: (c) => {
    const id = `manual-${Date.now().toString(36)}`
    set((st) => ({ manualCourses: [...st.manualCourses, { ...c, id }] }))
    void createManualCourse({ ...c, id }).catch(() => undefined)
    return id
  },
  removeManualCourse: (id) => {
    set((st) => {
      const { [id]: _drop, ...rest } = st.statuses
      void _drop
      return { manualCourses: st.manualCourses.filter((m) => m.id !== id), statuses: rest }
    })
    void deleteCourse(id).catch(() => undefined)
  },
  install: async (courseCode, packId) => {
    const res = await installPack(packId)
    set((st) => ({
      installedPacks: { ...st.installedPacks, [courseCode]: res.version },
      statuses: {
        ...st.statuses,
        [courseCode]: 'active',
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
    const [careerDetail, packs] = await Promise.all([
      getCareer(p.careerId),
      listPacks(p.careerId),
    ])
    set((st) => ({
      career: careerDetail,
      packs: Object.fromEntries(packs.map((k) => [k.course_code, k])),
      statuses: careerDetail ? { ...st.statuses, ...careerDetail.statuses } : st.statuses,
      installedPacks: careerDetail
        ? { ...st.installedPacks, ...careerDetail.installed_packs }
        : st.installedPacks,
    }))
  },
}))

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
