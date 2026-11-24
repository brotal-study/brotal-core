import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FilePlus2, Home, PackageOpen } from 'lucide-react'
import IngestModal from './IngestModal'
import { useAppStore } from '../../store/useAppStore'

interface Props {
  name: string
  code?: string
}

export default function EmptyCourse({ name, code }: Props) {
  const { profile } = useAppStore()
  const [ingestOpen, setIngestOpen] = useState(false)

  return (
    <main className="mx-auto flex max-w-md flex-col items-center gap-3 px-4 py-20 text-center">
      <PackageOpen size={36} className="text-slate-400" />
      <h1 className="text-xl font-semibold">{name}</h1>
      {code && <p className="font-mono text-xs text-slate-500">{code}</p>}
      <p className="text-sm text-slate-600 dark:text-slate-300">
        Este ramo aún no tiene un Pack instalado. Puedes crear su árbol de estudio subiendo tus propios apuntes (PDF,
        PPTX, DOCX, MD o TXT).
      </p>
      <div className="mt-2 flex flex-wrap justify-center gap-2">
        <Link
          to="/"
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 px-4 py-2 text-sm hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
        >
          <Home size={16} /> Volver a Mi Malla
        </Link>
        <button
          type="button"
          onClick={() => setIngestOpen(true)}
          className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
        >
          <FilePlus2 size={16} /> Crear desde tus archivos (PDF/PPTX)
        </button>
      </div>
      <IngestModal
        open={ingestOpen}
        onClose={() => setIngestOpen(false)}
        defaultCode={code ?? 'LOCAL101'}
        defaultTitle={name}
        careerId={profile?.careerId ?? null}
      />
    </main>
  )
}
