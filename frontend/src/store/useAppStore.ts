import { create } from 'zustand'

export type Theme = 'dark' | 'light'
export type CurriculumMode = 'realistic' | 'free'

interface AppState {
  theme: Theme
  curriculumMode: CurriculumMode
  activeCourseId: string | null
  setTheme: (t: Theme) => void
  toggleTheme: () => void
  setCurriculumMode: (m: CurriculumMode) => void
  setActiveCourse: (id: string | null) => void
}

const initialTheme = (): Theme =>
  localStorage.getItem('brotal_theme') === 'light' ? 'light' : 'dark'

function applyTheme(t: Theme) {
  localStorage.setItem('brotal_theme', t)
  document.documentElement.classList.toggle('dark', t === 'dark')
}

export const useAppStore = create<AppState>((set, get) => ({
  theme: initialTheme(),
  curriculumMode: 'realistic',
  activeCourseId: null,
  setTheme: (theme) => {
    applyTheme(theme)
    set({ theme })
  },
  toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
  setCurriculumMode: (curriculumMode) => set({ curriculumMode }),
  setActiveCourse: (activeCourseId) => set({ activeCourseId }),
}))
