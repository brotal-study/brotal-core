import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  BookOpen,
  ChevronDown,
  ChevronUp,
  Code2,
  ExternalLink,
  Layers,
  Tag,
  X,
} from 'lucide-react'
import type { PackNode } from '../../api/study'

interface Props {
  open: boolean
  onClose: () => void
  parentNodes: PackNode[]
  onNavigateNode?: (nodeId: string) => void
  hasDraftInProgress?: boolean
}

interface ExtractedCodeBlock {
  language: string
  code: string
}

function extractCodeBlocks(script: string): ExtractedCodeBlock[] {
  const blocks: ExtractedCodeBlock[] = []
  const regex = /```([a-zA-Z0-9_+-]*)[ \t]*\r?\n([\s\S]*?)```/g
  let match: RegExpExecArray | null
  while ((match = regex.exec(script)) !== null) {
    const lang = (match[1] || 'code').trim().toUpperCase()
    const code = match[2].trim()
    if (code) {
      blocks.push({ language: lang, code })
    }
  }
  return blocks
}

function extractKeyConceptChips(script: string): string[] {
  const withoutCode = script.replace(/```[\s\S]*?```/g, ' ')
  const regex = /\*\*([^*\n]{2,64})\*\*/g
  const seen = new Set<string>()
  const chips: string[] = []
  let match: RegExpExecArray | null
  while ((match = regex.exec(withoutCode)) !== null) {
    const cleaned = match[1]
      .replace(/^[\s:;,.()[\]-]+|[\s:;,.()[\]-]+$/g, '')
      .replace(/\s+/g, ' ')
      .trim()
    if (cleaned.length < 2) continue
    const key = cleaned.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    chips.push(cleaned)
    if (chips.length >= 12) break
  }
  return chips
}

export default function QuickReferenceDrawer({
  open,
  onClose,
  parentNodes,
  onNavigateNode,
  hasDraftInProgress = false,
}: Props) {
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({})
  const [confirmNodeId, setConfirmNodeId] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setConfirmNodeId(null)
      return
    }
    setExpandedIds((prev) => {
      if (parentNodes.length === 0) return prev
      const hasAny = parentNodes.some((p) => prev[p.id])
      if (hasAny) return prev
      return { ...prev, [parentNodes[0].id]: true }
    })
  }, [open, parentNodes])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  const toggleNode = (id: string) => {
    setExpandedIds((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const handleRequestNavigate = (nodeId: string) => {
    if (!onNavigateNode) return
    if (hasDraftInProgress) {
      setConfirmNodeId(nodeId)
      return
    }
    onClose()
    onNavigateNode(nodeId)
  }

  const handleConfirmNavigate = (nodeId: string) => {
    if (!onNavigateNode) return
    setConfirmNodeId(null)
    onClose()
    onNavigateNode(nodeId)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label="Apunte rápido de lecciones previas"
    >
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-slate-900/40 backdrop-blur-[1px] transition-opacity dark:bg-slate-950/65"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer panel */}
      <aside className="relative z-10 flex h-full w-full max-w-md flex-col border-l border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3.5 dark:border-slate-800">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
              <BookOpen size={16} className="shrink-0 text-indigo-600 dark:text-indigo-400" />
              <span className="truncate">Apunte rápido</span>
              <span className="rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 font-mono text-[11px] font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200">
                {parentNodes.length}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
              Referencia sintética de las clases previas sin perder tus respuestas del taller.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar apunte rápido"
            className="inline-flex shrink-0 items-center justify-center rounded-md border border-slate-200 p-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
          >
            <X size={16} />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {parentNodes.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 bg-slate-50/70 px-4 py-10 text-center dark:border-slate-700 dark:bg-slate-800/40">
              <Layers size={22} className="text-slate-400 dark:text-slate-500" />
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                Sin lecciones padre vinculadas
              </p>
              <p className="max-w-xs text-xs text-slate-500 dark:text-slate-400">
                Este taller no depende de nodos de teoría previos en el árbol de habilidades.
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {parentNodes.map((parent) => {
                const isExpanded = Boolean(expandedIds[parent.id])
                const chips = extractKeyConceptChips(parent.story_script || '')
                const codeBlocks = extractCodeBlocks(parent.story_script || '')
                const askingConfirm = confirmNodeId === parent.id

                return (
                  <section
                    key={parent.id}
                    className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50/60 dark:border-slate-700 dark:bg-slate-800/45"
                  >
                    <button
                      type="button"
                      aria-expanded={isExpanded}
                      onClick={() => toggleNode(parent.id)}
                      className="flex w-full items-start justify-between gap-2 px-3.5 py-3 text-left hover:bg-slate-100/80 dark:hover:bg-slate-800/80"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                            {parent.title}
                          </span>
                          <span className="rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[10px] text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
                            {parent.block}
                          </span>
                        </div>
                        {parent.summary && (
                          <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-600 dark:text-slate-300">
                            {parent.summary}
                          </p>
                        )}
                      </div>
                      <span className="mt-0.5 shrink-0 text-slate-400 dark:text-slate-500">
                        {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                      </span>
                    </button>

                    {isExpanded && (
                      <div className="flex flex-col gap-3 border-t border-slate-200 bg-white px-3.5 py-3 dark:border-slate-700/80 dark:bg-slate-900/70">
                        {chips.length > 0 && (
                          <div className="flex flex-col gap-1.5">
                            <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                              <Tag size={11} />
                              Conceptos clave
                            </span>
                            <div className="flex flex-wrap gap-1.5">
                              {chips.map((chip, idx) => (
                                <span
                                  key={idx}
                                  className="rounded-full border border-indigo-200 bg-indigo-50/80 px-2.5 py-0.5 text-xs font-medium text-indigo-900 dark:border-indigo-800/80 dark:bg-indigo-950/60 dark:text-indigo-200"
                                >
                                  {chip}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}

                        {codeBlocks.length > 0 && (
                          <div className="flex flex-col gap-2">
                            <span className="inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                              <Code2 size={11} />
                              Sintaxis y ejemplos
                            </span>
                            {codeBlocks.map((block, bIdx) => (
                              <div
                                key={bIdx}
                                className="overflow-hidden rounded-md border border-slate-200 bg-slate-950 dark:border-slate-700"
                              >
                                <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900 px-2.5 py-1">
                                  <span className="font-mono text-[10px] font-semibold uppercase tracking-wider text-slate-300">
                                    {block.language}
                                  </span>
                                </div>
                                <pre className="overflow-x-auto p-2.5 font-mono text-xs leading-relaxed text-slate-100">
                                  <code>{block.code}</code>
                                </pre>
                              </div>
                            ))}
                          </div>
                        )}

                        {chips.length === 0 && codeBlocks.length === 0 && (
                          <p className="text-xs text-slate-500 dark:text-slate-400">
                            Esta lección no contiene bloques de código ni términos destacados; revisa el resumen superior o abre la clase completa.
                          </p>
                        )}

                        {onNavigateNode && (
                          <div className="border-t border-slate-100 pt-2.5 dark:border-slate-800">
                            {askingConfirm ? (
                              <div className="flex flex-col gap-2 rounded-md border border-amber-300 bg-amber-50/80 p-2.5 text-xs text-amber-950 dark:border-amber-700/80 dark:bg-amber-950/40 dark:text-amber-200">
                                <div className="flex items-start gap-1.5">
                                  <AlertTriangle
                                    size={14}
                                    className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400"
                                  />
                                  <span>
                                    Tienes un intento en curso en este taller. Si abres la clase completa se descartarán tus respuestas actuales.
                                  </span>
                                </div>
                                <div className="flex flex-wrap items-center gap-2">
                                  <button
                                    type="button"
                                    onClick={() => handleConfirmNavigate(parent.id)}
                                    className="rounded bg-amber-700 px-2.5 py-1 text-xs font-semibold text-white hover:bg-amber-600 dark:bg-amber-500 dark:text-slate-950 dark:hover:bg-amber-400"
                                  >
                                    Sí, abrir clase completa
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setConfirmNodeId(null)}
                                    className="rounded border border-amber-300 bg-white px-2.5 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100 dark:border-amber-700 dark:bg-slate-900 dark:text-amber-200 dark:hover:bg-amber-950/70"
                                  >
                                    Seguir en el taller
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => handleRequestNavigate(parent.id)}
                                className="inline-flex items-center gap-1.5 rounded border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                              >
                                <ExternalLink size={12} />
                                Abrir clase completa
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </section>
                )
              })}
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}
