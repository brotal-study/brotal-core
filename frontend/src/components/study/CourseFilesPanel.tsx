import { useCallback, useEffect, useState } from 'react'
import { FilePlus2, FileText, FolderOpen, Loader2, Trash2, X } from 'lucide-react'
import {
  deleteCourseFile,
  getCourseFiles,
  type ProcessedFileSummary,
} from '../../api/curriculum'

interface Props {
  courseId: string
  onOpenIngest: () => void
  onFilesChange?: (count: number) => void
  refreshTrigger?: number
}

export default function CourseFilesPanel({
  courseId,
  onOpenIngest,
  onFilesChange,
  refreshTrigger = 0,
}: Props) {
  const [files, setFiles] = useState<ProcessedFileSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [deletingFile, setDeletingFile] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadFiles = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getCourseFiles(courseId)
      setFiles(res.files)
      onFilesChange?.(res.files.length)
    } catch {
      setFiles([])
      onFilesChange?.(0)
    } finally {
      setLoading(false)
    }
  }, [courseId, onFilesChange])

  useEffect(() => {
    void loadFiles()
  }, [loadFiles, refreshTrigger])

  const handleDelete = async (filename: string) => {
    setDeletingFile(filename)
    setError(null)
    try {
      const res = await deleteCourseFile(courseId, filename)
      setFiles(res.files)
      onFilesChange?.(res.files.length)
    } catch {
      setError(`No se pudo eliminar ${filename}.`)
    } finally {
      setDeletingFile(null)
    }
  }

  return (
    <div className="flex flex-col gap-2.5 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
      <div className="flex items-center justify-between gap-2">
        <h3 className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
          <FolderOpen size={14} />
          Archivos subidos ({files.length})
        </h3>
        <button
          type="button"
          onClick={onOpenIngest}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <FilePlus2 size={13} />
          {files.length > 0 ? 'Agregar o reemplazar archivos' : 'Subir archivos'}
        </button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-2 text-xs text-slate-500">
          <Loader2 size={14} className="animate-spin" />
          Consultando archivos indexados en FTS5...
        </div>
      ) : files.length === 0 ? (
        <p className="text-xs text-slate-500">
          Aún no hay archivos locales indexados para este ramo.
        </p>
      ) : (
        <ul className="max-h-48 divide-y divide-slate-200 overflow-y-auto rounded border border-slate-200 text-xs dark:divide-slate-800 dark:border-slate-800">
          {files.map((f) => (
            <li
              key={f.filename}
              className="flex items-center justify-between gap-2 px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 truncate font-medium">
                  <FileText size={13} className="shrink-0 text-slate-500" />
                  <span className="truncate">{f.filename}</span>
                </div>
                <div className="mt-0.5 font-mono text-[11px] text-slate-500">
                  {f.sections} secc. · {f.chars.toLocaleString('es-CL')} chars
                </div>
              </div>
              <button
                type="button"
                disabled={deletingFile === f.filename}
                onClick={() => handleDelete(f.filename)}
                title={`Eliminar ${f.filename} del índice local`}
                aria-label={`Eliminar ${f.filename}`}
                className="inline-flex shrink-0 items-center gap-1 rounded border border-slate-200 px-2 py-1 text-[11px] text-slate-600 hover:border-rose-300 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:border-rose-800 dark:hover:bg-rose-950/40 dark:hover:text-rose-300"
              >
                {deletingFile === f.filename ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <Trash2 size={12} />
                )}
                Quitar
              </button>
            </li>
          ))}
        </ul>
      )}

      {error && <p className="text-xs text-rose-600 dark:text-rose-400">{error}</p>}
    </div>
  )
}

export function CourseFilesModal({
  open,
  onClose,
  courseId,
  courseTitle,
  onOpenIngest,
  refreshTrigger = 0,
}: {
  open: boolean
  onClose: () => void
  courseId: string
  courseTitle: string
  onOpenIngest: () => void
  refreshTrigger?: number
}) {
  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label={`Archivos de ${courseTitle}`}
        onClick={(e) => e.stopPropagation()}
        className="flex w-full max-w-lg flex-col gap-4 rounded-lg border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-800 dark:bg-slate-900"
      >
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 pb-3 dark:border-slate-800">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">Archivos del ramo · {courseTitle}</h2>
            <p className="text-xs text-slate-500">
              Agrega nuevos apuntes semana a semana conservando tu progreso o gestiona los archivos indexados en FTS5.
            </p>
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

        <CourseFilesPanel
          courseId={courseId}
          refreshTrigger={refreshTrigger}
          onOpenIngest={onOpenIngest}
        />
      </div>
    </div>
  )
}
