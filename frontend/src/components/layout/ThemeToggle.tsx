import { Moon, Sun } from 'lucide-react'
import { useAppStore } from '../../store/useAppStore'

export default function ThemeToggle() {
  const { theme, toggleTheme } = useAppStore()
  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label="Cambiar tema"
      className="rounded p-2 hover:bg-slate-200 dark:hover:bg-slate-800"
    >
      {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  )
}
