import { ChevronDown, Home } from 'lucide-react'
import { Link } from 'react-router-dom'
import ThemeToggle from './ThemeToggle'

// TODO(#5): el desplegable lista solo ramos con status 'active' (GET /api/v1/courses?status=active) + Ctrl+K.
export default function TopBar() {
  return (
    <header className="flex items-center gap-3 border-b border-slate-200 px-4 py-2 dark:border-slate-800">
      <Link to="/" className="flex items-center gap-2 rounded px-2 py-1 hover:bg-slate-200 dark:hover:bg-slate-800">
        <Home size={18} />
        <span>Malla</span>
      </Link>
      <span className="text-slate-400">|</span>
      <button type="button" className="flex items-center gap-2 rounded px-2 py-1 hover:bg-slate-200 dark:hover:bg-slate-800">
        <span>Sin ramo activo</span>
        <ChevronDown size={16} />
      </button>
      <div className="ml-auto">
        <ThemeToggle />
      </div>
    </header>
  )
}
