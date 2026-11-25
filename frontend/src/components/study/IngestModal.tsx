import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  FilePlus2,
  FileText,
  Layers,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import {
  getCourseFiles,
  ingestLocalFiles,
  type IngestLocalResponse,
  type IngestMode,
} from '../../api/curriculum'
import { useAppStore } from '../../store/useAppStore'
import { useStudyStore } from '../../store/useStudyStore'

interface Props {
  open: boolean
  onClose: () => void
  defaultCode?: string
  defaultTitle?: string
  careerId?: string | null
  onIngested?: (res: IngestLocalResponse) => void
}

export default function IngestModal({
  open,
  onClose,
  defaultCode = '',
  defaultTitle = '',
  careerId = null,
  onIngested,
}: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const { installedPacks, setStatus, setActiveCourse, hydrate } = useAppStore()
  const { tree: currentTree, load: loadStudyTree } = useStudyStore()

  const [code, setCode] = useState(defaultCode)
  const [title, setTitle] = useState(defaultTitle)
  const [metaphor, setMetaphor] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [mode, setMode] = useState<IngestMode>('append')
  const [existingFilesCount, setExistingFilesCount] = useState(0)
  const [busy, setBusy] = useState(false)
  const [elapsedSec, setElapsedSec] = useState(0)
  const [err, setErr] = useState<string | null>(null)
  const [result, setResult] = useState<IngestLocalResponse | null>(null)

  const targetCode = (code.trim() || defaultCode).toUpperCase()
  const hasTreeNodes = Boolean(
    currentTree &&
      currentTree.nodes.length > 0 &&
      (currentTree.course_code.toUpperCase() === targetCode ||
        currentTree.course_id.toUpperCase() === targetCode),
  )
  const hasExistingContent =
    Boolean(targetCode && installedPacks[targetCode]) || hasTreeNodes || existingFilesCount > 0

  useEffect(() => {
    if (open) {
      setCode(defaultCode)
      setTitle(defaultTitle)
      setMode('append')
      setErr(null)
    }
  }, [open, defaultCode, defaultTitle])

  useEffect(() => {
    if (!open || !targetCode) {
      setExistingFilesCount(0)
      return
    }
    let cancelled = false
    getCourseFiles(targetCode)
      .then((res) => {
        if (!cancelled) setExistingFilesCount(res.files.length)
      })
      .catch(() => {
        if (!cancelled) setExistingFilesCount(0)
      })
    return () => {
      cancelled = true
    }
  }, [open, targetCode])

  useEffect(() => {
    if (!busy) {
      setElapsedSec(0)
      return
    }
    const start = Date.now()
    const timer = setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - start) / 1000))
    }, 500)
    return () => clearInterval(timer)
  }, [busy])

  if (!open) return null

  const activeStep = elapsedSec < 2 ? 1 : elapsedSec < 4 ? 2 : 3
  const effectiveMode: IngestMode = hasExistingContent ? mode : 'replace'

  const onFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files ?? [])
    if (selected.length > 0) {
      setFiles((prev) => [...prev, ...selected])
      setErr(null)
    }
  }

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (files.length === 0) {
      setErr('Selecciona al menos un archivo (.pdf, .pptx, .docx, .md o .txt).')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      const res = await ingestLocalFiles({
        course_code: code.trim() || defaultCode || 'LOCAL101',
        title: title.trim() || defaultTitle || 'Ramo Local',
        career_id: careerId,
        world_metaphor: metaphor.trim() || undefined,
        mode: effectiveMode,
        files,
      })
      setResult(res)
      setStatus(res.course_code, 'active')
      await hydrate()
      onIngested?.(res)
    } catch (exc) {
      setErr(exc instanceof Error ? exc.message : 'Error al procesar los archivos.')
    } finally {
      setBusy(false)
    }
  }

  const goToTree = async () => {
    if (!result) return
    const targetKey = defaultCode || result.course_code || result.course_id
    const targetPath = `/course/${encodeURIComponent(targetKey)}`
    setActiveCourse(targetKey)
    onClose()
    if (location.pathname === targetPath) {
      await loadStudyTree(targetKey)
    } else {
      navigate(targetPath)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-label="Crear árbol desde apuntes locales"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-800 dark:bg-slate-900"
      >
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 pb-3 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <FilePlus2 size={18} className="text-slate-600 dark:text-slate-300" />
            <div>
              <h2 className="text-base font-semibold">Ingesta Local de Apuntes (BYOF)</h2>
              <p className="text-xs text-slate-500">
                Extrae secciones a SQLite FTS5 y genera un árbol de 6 a 16 nodos conversados.
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Cerrar"
            onClick={onClose}
            className="rounded p-1 hover:bg-slate-200 dark:hover:bg-slate-800"
          >
            <X size={18} />
          </button>
        </header>

        {!result ? (
          <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-4">
            <div className="flex items-start gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
              <ShieldAlert size={15} className="mt-0.5 shrink-0" />
              <span>
                Tus archivos originales se procesan en local y <strong>nunca</strong> se incluyen ni se exportan en un
                Course Pack comunitario.
              </span>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <label className="flex flex-col gap-1 text-xs">
                <span className="font-medium text-slate-600 dark:text-slate-300">Código</span>
                <input
                  type="text"
                  required
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="INF2236"
                  className="rounded border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs sm:col-span-2">
                <span className="font-medium text-slate-600 dark:text-slate-300">Nombre del ramo</span>
                <input
                  type="text"
                  required
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Programación Avanzada en Java"
                  className="rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs dark:border-slate-700 dark:bg-slate-950"
                />
              </label>
            </div>

            <label className="flex flex-col gap-1 text-xs">
              <span className="font-medium text-slate-600 dark:text-slate-300">
                Metáfora del mundo (opcional)
              </span>
              <input
                type="text"
                value={metaphor}
                onChange={(e) => setMetaphor(e.target.value)}
                placeholder="Ej. Fábrica Modular JVM (clases como moldes y objetos en la línea de ensamblaje)"
                className="rounded border border-slate-300 bg-white px-2.5 py-1.5 text-xs dark:border-slate-700 dark:bg-slate-950"
              />
            </label>

            {hasExistingContent && (
              <div className="flex flex-col gap-2">
                <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  Modo de actualización del ramo
                </span>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Modo de ingesta">
                  <button
                    type="button"
                    role="radio"
                    aria-checked={mode === 'append'}
                    onClick={() => setMode('append')}
                    className={`flex flex-col items-start gap-1 rounded-md border p-2.5 text-left text-xs transition ${
                      mode === 'append'
                        ? 'border-indigo-600 bg-indigo-50/70 text-indigo-950 dark:border-indigo-500 dark:bg-indigo-950/40 dark:text-indigo-100'
                        : 'border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800/50'
                    }`}
                  >
                    <span className="inline-flex items-center gap-1.5 font-semibold">
                      <Layers size={14} className="text-indigo-600 dark:text-indigo-400" />
                      Agregar al ramo (conserva tu progreso)
                    </span>
                    <span className="text-[11px] text-slate-600 dark:text-slate-400">
                      Suma archivos nuevos y añade 2 a 6 nodos conectados sin borrar tu progreso 0/3 a 3/3.
                    </span>
                  </button>

                  <button
                    type="button"
                    role="radio"
                    aria-checked={mode === 'replace'}
                    onClick={() => setMode('replace')}
                    className={`flex flex-col items-start gap-1 rounded-md border p-2.5 text-left text-xs transition ${
                      mode === 'replace'
                        ? 'border-amber-600 bg-amber-50/70 text-amber-950 dark:border-amber-500 dark:bg-amber-950/40 dark:text-amber-100'
                        : 'border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800/50'
                    }`}
                  >
                    <span className="inline-flex items-center gap-1.5 font-semibold">
                      <RefreshCw size={14} className="text-amber-600 dark:text-amber-400" />
                      Reemplazar todo (reconstruye desde cero)
                    </span>
                    <span className="text-[11px] text-slate-600 dark:text-slate-400">
                      Sustituye todos los archivos anteriores y regenera el árbol completo.
                    </span>
                  </button>
                </div>

                {mode === 'replace' && (
                  <div className="flex items-center gap-2 rounded border border-amber-300 bg-amber-50 px-2.5 py-1.5 text-[11px] text-amber-900 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-200">
                    <AlertTriangle size={13} className="shrink-0 text-amber-600 dark:text-amber-400" />
                    <span>
                      Advertencia: se reemplazarán los archivos indexados previos y se reconstruirán los nodos desde cero.
                    </span>
                  </div>
                )}
              </div>
            )}

            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                Archivos de apuntes (.pdf, .pptx, .docx, .md, .txt)
              </span>
              <label className="flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-slate-400 p-4 text-center text-xs hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800/50">
                <Upload size={18} className="text-slate-500" />
                <span className="font-medium">Seleccionar archivos de tu equipo</span>
                <span className="text-[11px] text-slate-500">Sin PyTorch · Extracción instantánea por página/slide</span>
                <input
                  type="file"
                  multiple
                  accept=".pdf,.pptx,.docx,.md,.txt"
                  onChange={onFileSelect}
                  className="hidden"
                />
              </label>

              {files.length > 0 && (
                <ul className="max-h-36 divide-y divide-slate-200 overflow-y-auto rounded border border-slate-200 text-xs dark:divide-slate-800 dark:border-slate-800">
                  {files.map((f, i) => (
                    <li key={`${f.name}-${i}`} className="flex items-center justify-between px-3 py-1.5">
                      <span className="inline-flex items-center gap-1.5 truncate">
                        <FileText size={13} className="shrink-0 text-slate-500" />
                        <span className="truncate">{f.name}</span>
                        <span className="text-[11px] text-slate-400">({Math.max(1, Math.round(f.size / 1024))} KB)</span>
                      </span>
                      <button
                        type="button"
                        onClick={() => removeFile(i)}
                        className="text-slate-400 hover:text-rose-600"
                        aria-label={`Quitar ${f.name}`}
                      >
                        <Trash2 size={13} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {busy && (
              <div
                role="status"
                aria-live="polite"
                className="flex flex-col gap-2 rounded-md border border-indigo-200 bg-indigo-50/70 p-3 text-xs text-indigo-950 dark:border-indigo-800/70 dark:bg-indigo-950/40 dark:text-indigo-200"
              >
                <div className="flex items-center justify-between font-medium">
                  <span className="inline-flex items-center gap-1.5">
                    <Loader2 size={14} className="animate-spin text-indigo-600 dark:text-indigo-400" />
                    Procesando tus apuntes...
                  </span>
                  <span className="inline-flex items-center gap-1 font-mono text-[11px]">
                    <Clock size={12} /> {elapsedSec}s
                  </span>
                </div>
                <ol className="space-y-1 text-[11px]">
                  <li className={activeStep >= 1 ? 'font-semibold' : 'opacity-60'}>
                    1. Extrayendo texto de {files.length} archivo(s)
                  </li>
                  <li className={activeStep >= 2 ? 'font-semibold' : 'opacity-60'}>
                    2. Indexando secciones en SQLite FTS5
                  </li>
                  <li className={activeStep >= 3 ? 'font-semibold' : 'opacity-60'}>
                    3. Generando árbol y exámenes con IA...
                  </li>
                </ol>
              </div>
            )}

            {err && <p className="text-xs font-medium text-rose-600 dark:text-rose-400">{err}</p>}

            <div className="flex justify-end gap-2 border-t border-slate-200 pt-3 dark:border-slate-800">
              <button
                type="button"
                disabled={busy}
                onClick={onClose}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={busy || files.length === 0}
                className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
              >
                {busy && <Loader2 size={14} className="animate-spin" />}
                {busy
                  ? `Procesando (${elapsedSec}s)...`
                  : effectiveMode === 'append'
                    ? 'Agregar material al árbol'
                    : 'Generar árbol de estudio'}
              </button>
            </div>
          </form>
        ) : (
          <div className="mt-4 flex flex-col gap-4">
            <div className="flex items-start gap-2.5 rounded-md border border-emerald-300 bg-emerald-50 p-3 text-xs text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200">
              <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
              <div>
                <div className="text-sm font-semibold">
                  {result.mode === 'append'
                    ? `Se agregaron ${result.added_nodes ?? 0} nodos nuevos · ${result.node_count} nodos en total (${result.chunks_indexed} secciones en FTS5)`
                    : `Árbol generado: ${result.node_count} nodos (${result.chunks_indexed} secciones en FTS5)`}
                </div>
                <p className="mt-0.5">
                  Motor utilizado: <code className="font-mono">{result.provider}</code> · Modo:{' '}
                  <strong>{result.mode === 'append' ? 'Incremental (progreso conservado)' : 'Árbol completo'}</strong>
                </p>
              </div>
            </div>

            <div>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Archivos procesados ({result.processed_files.length})
              </h3>
              <ul className="divide-y divide-slate-200 rounded border border-slate-200 text-xs dark:divide-slate-800 dark:border-slate-800">
                {result.processed_files.map((pf, idx) => (
                  <li key={idx} className="flex items-center justify-between px-3 py-2">
                    <span className="inline-flex items-center gap-1.5 font-medium">
                      <FileText size={13} className="text-slate-500" />
                      {pf.filename}
                    </span>
                    <span className="font-mono text-[11px] text-slate-500">
                      {pf.sections} secc. · {pf.chars} chars
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setResult(null)
                  setFiles([])
                }}
                className="rounded-md border border-slate-300 px-3 py-2 text-xs hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
              >
                Subir más archivos
              </button>
              <button
                type="button"
                onClick={goToTree}
                className="inline-flex items-center justify-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
              >
                Estudiar ramo ahora <ArrowRight size={16} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
