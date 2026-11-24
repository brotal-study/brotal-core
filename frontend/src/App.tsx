import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import TopBar from './components/layout/TopBar'
import CurriculumPage from './pages/CurriculumPage'
import CourseStudyPage from './pages/CourseStudyPage'
import OnboardingPage from './pages/OnboardingPage'
import { useAppStore } from './store/useAppStore'

export default function App() {
  const hydrated = useAppStore((s) => s.hydrated)
  const hydrate = useAppStore((s) => s.hydrate)
  const profile = useAppStore((s) => s.profile)
  const theme = useAppStore((s) => s.theme)

  useEffect(() => {
    void hydrate()
  }, [hydrate])

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
  }, [theme])

  if (!hydrated) {
    return (
      <>
        <TopBar />
        <main className="p-6 text-sm text-slate-500">Cargando perfil local...</main>
      </>
    )
  }

  return (
    <>
      <TopBar />
      <Routes>
        <Route path="/onboarding" element={<OnboardingPage />} />
        <Route path="/" element={profile ? <CurriculumPage /> : <Navigate to="/onboarding" replace />} />
        <Route path="/course/:courseId" element={profile ? <CourseStudyPage /> : <Navigate to="/onboarding" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
