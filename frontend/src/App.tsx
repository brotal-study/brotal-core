import { Route, Routes } from 'react-router-dom'
import TopBar from './components/layout/TopBar'
import CurriculumPage from './pages/CurriculumPage'

export default function App() {
  return (
    <>
      <TopBar />
      <Routes>
        <Route path="/" element={<CurriculumPage />} />
      </Routes>
    </>
  )
}
