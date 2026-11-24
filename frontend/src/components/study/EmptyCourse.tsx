import { Link } from 'react-router-dom'
import { FilePlus2, Home, PackageOpen } from 'lucide-react'

interface Props {
  name: string
  code?: string
}

export default function EmptyCourse({ name, code }: Props) {
  return (
    <main className="mx-auto flex max-w-md flex-col items-center gap-3 px-4 py-20 text-center">
      <PackageOpen size={36} className="text-slate-400" />
      <h1 className="text-xl font-semibold">{name}</h1>
      {code && <p className="font-mono text-xs text-slate-500">{code}</p>}
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Este ramo aún no tiene un Pack instalado, así que todavía no hay árbol de estudio.
      </p>
      <div className="mt-2 flex flex-wrap justify-center gap-2">
        <Link to="/" className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300">
          <Home size={16} /> Volver a Mi Malla
        </Link>
        <button type="button" disabled title="Disponible en v1.0" className="inline-flex items-center gap-2 rounded-md border border-dashed border-slate-400 px-4 py-2 text-sm text-slate-500 opacity-70">
          <FilePlus2 size={16} /> Crear desde tus archivos (v1.0)
        </button>
      </div>
    </main>
  )
}
