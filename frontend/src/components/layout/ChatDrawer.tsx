import { useEffect, useRef, useState } from 'react'
import {
  ArrowRight,
  Info,
  Loader2,
  Maximize2,
  MessageSquare,
  Minimize2,
  Send,
  Trash2,
  X,
} from 'lucide-react'
import {
  clearChatHistory,
  getChatHistory,
  sendChatMessage,
  type ChatMessage,
  type SuggestedNode,
} from '../../api/study'
import { useStudyStore } from '../../store/useStudyStore'
import MarkdownView from '../common/MarkdownView'

interface Props {
  open: boolean
  onClose: () => void
  courseId: string
  courseTitle: string
  nodeId: string | null
  nodeTitle: string | null
  initialPrompt?: string | null
  contextBanner?: string | null
  autoSendTrigger?: number
  onSelectNode?: (nodeId: string) => void
}

const NODE_MENTION_RE = /\[\[node:([^|\]]+)\|([^\]]+)\]\]/g
const CHAT_WIDTH_STORAGE_KEY = 'brotal_chat_width'
const MIN_CHAT_WIDTH = 340
const DEFAULT_CHAT_WIDTH = 448
const EXPANDED_CHAT_WIDTH = 768

function getMaxChatWidth(): number {
  if (typeof window === 'undefined') return 1200
  return Math.max(MIN_CHAT_WIDTH, Math.floor(window.innerWidth * 0.9))
}

function clampChatWidth(rawWidth: number): number {
  return Math.min(getMaxChatWidth(), Math.max(MIN_CHAT_WIDTH, Math.round(rawWidth)))
}

function readInitialChatWidth(): number {
  try {
    const raw = window.localStorage.getItem(CHAT_WIDTH_STORAGE_KEY)
    if (raw) {
      const parsed = Number(raw)
      if (Number.isFinite(parsed) && parsed > 0) {
        return clampChatWidth(parsed)
      }
    }
  } catch {
    // Ignore storage access errors
  }
  return clampChatWidth(DEFAULT_CHAT_WIDTH)
}

function persistChatWidth(width: number): void {
  try {
    window.localStorage.setItem(CHAT_WIDTH_STORAGE_KEY, String(Math.round(width)))
  } catch {
    // Ignore storage access errors
  }
}

function extractNodesFromText(text: string): SuggestedNode[] {
  const seen = new Set<string>()
  const out: SuggestedNode[] = []
  for (const match of text.matchAll(NODE_MENTION_RE)) {
    const id = match[1]?.trim()
    const title = match[2]?.trim()
    if (id && !seen.has(id)) {
      seen.add(id)
      out.push({ id, title: title || id })
    }
  }
  return out
}

export default function ChatDrawer({
  open,
  onClose,
  courseId,
  courseTitle,
  nodeId,
  nodeTitle,
  initialPrompt = null,
  contextBanner = null,
  autoSendTrigger = 0,
  onSelectNode,
}: Props) {
  const selectInStore = useStudyStore((s) => s.select)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [suggestedByMsg, setSuggestedByMsg] = useState<Record<number, SuggestedNode[]>>({})
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [width, setWidth] = useState<number>(() => readInitialChatWidth())
  const [expanded, setExpanded] = useState<boolean>(() => readInitialChatWidth() >= EXPANDED_CHAT_WIDTH - 24)
  const [isResizing, setIsResizing] = useState(false)
  const [provider, setProvider] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const lastAutoSentTriggerRef = useRef(0)
  const widthRef = useRef(width)
  widthRef.current = width
  const savedNormalWidthRef = useRef(
    width < EXPANDED_CHAT_WIDTH - 24 ? width : DEFAULT_CHAT_WIDTH,
  )
  const resizeCleanupRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    const handleWindowResize = () => {
      const clamped = clampChatWidth(widthRef.current)
      if (clamped !== widthRef.current) {
        widthRef.current = clamped
        setWidth(clamped)
        setExpanded(clamped >= EXPANDED_CHAT_WIDTH - 24)
      }
    }
    window.addEventListener('resize', handleWindowResize)
    return () => {
      window.removeEventListener('resize', handleWindowResize)
      resizeCleanupRef.current?.()
      resizeCleanupRef.current = null
    }
  }, [])

  const handleToggleExpand = () => {
    if (expanded) {
      const target = clampChatWidth(
        savedNormalWidthRef.current < EXPANDED_CHAT_WIDTH - 24
          ? savedNormalWidthRef.current
          : DEFAULT_CHAT_WIDTH,
      )
      widthRef.current = target
      setWidth(target)
      setExpanded(false)
      persistChatWidth(target)
    } else {
      if (widthRef.current < EXPANDED_CHAT_WIDTH - 24) {
        savedNormalWidthRef.current = widthRef.current
      }
      const target = clampChatWidth(Math.max(EXPANDED_CHAT_WIDTH, widthRef.current))
      widthRef.current = target
      setWidth(target)
      setExpanded(true)
      persistChatWidth(target)
    }
  }

  const handleResizePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    resizeCleanupRef.current?.()
    setIsResizing(true)

    const onPointerMove = (moveEvent: PointerEvent) => {
      const next = clampChatWidth(window.innerWidth - moveEvent.clientX)
      widthRef.current = next
      setWidth(next)
      const isNowExpanded = next >= EXPANDED_CHAT_WIDTH - 24
      setExpanded(isNowExpanded)
      if (!isNowExpanded) {
        savedNormalWidthRef.current = next
      }
    }

    const finishResize = () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', finishResize)
      window.removeEventListener('pointercancel', finishResize)
      resizeCleanupRef.current = null
      setIsResizing(false)
      persistChatWidth(widthRef.current)
    }

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', finishResize)
    window.addEventListener('pointercancel', finishResize)
    resizeCleanupRef.current = () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', finishResize)
      window.removeEventListener('pointercancel', finishResize)
    }
  }

  const handleGoToNode = (targetNodeId: string) => {
    if (onSelectNode) {
      onSelectNode(targetNodeId)
    } else {
      selectInStore(targetNodeId)
    }
  }

  const sendDirect = async (rawText: string) => {
    const text = rawText.trim()
    if (!text || busy) return
    setBusy(true)
    setErr(null)
    setInput('')
    const payloadText =
      contextBanner && !text.includes(contextBanner.slice(0, 24))
        ? `${text}\n\n[Contexto de referencia: ${contextBanner}]`
        : text
    try {
      const res = await sendChatMessage(courseId, payloadText, nodeId)
      setMessages((prev) => [...prev, res.user_message, res.assistant_message])
      if (res.suggested_nodes && res.suggested_nodes.length > 0) {
        setSuggestedByMsg((prev) => ({
          ...prev,
          [res.assistant_message.id]: res.suggested_nodes ?? [],
        }))
      }
      setProvider(res.provider)
    } catch {
      setErr('No se pudo enviar el mensaje al tutor.')
      setInput(text)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!open || !courseId) return
    setErr(null)
    void getChatHistory(courseId)
      .then((hist) => setMessages(hist))
      .catch(() => setErr('No se pudo cargar el historial del tutor.'))
  }, [open, courseId])

  useEffect(() => {
    if (!open || !initialPrompt) return
    if (autoSendTrigger > 0 && lastAutoSentTriggerRef.current !== autoSendTrigger) {
      lastAutoSentTriggerRef.current = autoSendTrigger
      void sendDirect(initialPrompt)
    } else if (autoSendTrigger === 0) {
      setInput(initialPrompt)
      setTimeout(() => inputRef.current?.focus(), 60)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialPrompt, autoSendTrigger])

  useEffect(() => {
    if (open) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, open])

  if (!open) return null

  const send = async (e: React.FormEvent) => {
    e.preventDefault()
    await sendDirect(input)
  }

  const handleClear = async () => {
    setBusy(true)
    try {
      await clearChatHistory(courseId)
      setMessages([])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <aside
        role="dialog"
        aria-label="Chat Tutor del Ramo"
        onClick={(e) => e.stopPropagation()}
        style={{ width: `${width}px`, maxWidth: '90vw' }}
        className={`relative flex h-full flex-col border-l border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900 ${
          isResizing ? 'select-none' : 'transition-[width] duration-200'
        }`}
      >
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Redimensionar panel del tutor"
          title="Arrastra para ajustar el ancho del panel"
          onPointerDown={handleResizePointerDown}
          className={`group absolute inset-y-0 left-0 z-10 w-2 -translate-x-1/2 cursor-col-resize touch-none ${
            isResizing ? 'bg-indigo-500/35' : 'hover:bg-indigo-500/25'
          }`}
        >
          <span
            className={`pointer-events-none absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 transition-colors ${
              isResizing
                ? 'bg-indigo-500 dark:bg-indigo-400'
                : 'bg-transparent group-hover:bg-indigo-500/70 dark:group-hover:bg-indigo-400/70'
            }`}
          />
        </div>
        <header className="flex items-start justify-between gap-2 border-b border-slate-200 p-4 dark:border-slate-800">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-sm font-semibold">
              <MessageSquare size={16} />
              <span className="truncate">Tutor Socrático · {courseTitle}</span>
            </div>
            <p className="mt-0.5 truncate text-xs text-slate-500">
              {nodeTitle ? `Contexto: ${nodeTitle}` : 'Contexto transversal del ramo'}
              {provider ? ` · Motor: ${provider}` : ''}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              title={expanded ? 'Contraer panel del tutor' : 'Expandir panel para leer código'}
              aria-label={expanded ? 'Contraer panel del tutor' : 'Expandir panel del tutor'}
              onClick={handleToggleExpand}
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            >
              {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
            {messages.length > 0 && (
              <button
                type="button"
                title="Limpiar historial de chat"
                disabled={busy}
                onClick={handleClear}
                className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-rose-600 dark:hover:bg-slate-800"
              >
                <Trash2 size={15} />
              </button>
            )}
            <button
              type="button"
              aria-label="Cerrar tutor"
              onClick={onClose}
              className="rounded p-1.5 hover:bg-slate-200 dark:hover:bg-slate-800"
            >
              <X size={18} />
            </button>
          </div>
        </header>

        {contextBanner && (
          <div className="flex items-start gap-2 border-b border-indigo-200 bg-indigo-50/80 px-4 py-2.5 text-xs text-indigo-950 dark:border-indigo-800/70 dark:bg-indigo-950/40 dark:text-indigo-200">
            <Info size={14} className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
            <div className="min-w-0 flex-1 break-words leading-relaxed">{contextBanner}</div>
          </div>
        )}

        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.length === 0 && (
            <div className="rounded-md border border-dashed border-slate-300 p-3 text-xs text-slate-500 dark:border-slate-700">
              Pregunta cualquier duda sobre el nodo actual o tus apuntes del ramo. El tutor usa la historia del nodo,
              el índice FTS5 local y las últimas 10 interacciones sin salir de tu pantalla.
            </div>
          )}
          {messages.map((m) => {
            const suggestions =
              m.role === 'assistant'
                ? (suggestedByMsg[m.id] ?? extractNodesFromText(m.content))
                : []
            return (
              <div
                key={m.id}
                className={`flex flex-col rounded-lg px-3 py-2 text-sm ${
                  m.role === 'user'
                    ? 'ml-8 bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                    : 'mr-6 border border-slate-200 bg-slate-50 text-slate-800 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-100'
                }`}
              >
                {m.role === 'assistant' ? (
                  <MarkdownView content={m.content} onSelectNode={handleGoToNode} />
                ) : (
                  <div className="whitespace-pre-wrap break-words leading-relaxed">{m.content}</div>
                )}
                {suggestions.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5 border-t border-slate-200/80 pt-2 dark:border-slate-700/80">
                    {suggestions.map((sn) => (
                      <button
                        key={sn.id}
                        type="button"
                        onClick={() => handleGoToNode(sn.id)}
                        className="inline-flex items-center gap-1 rounded-md border border-indigo-300 bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-900 transition-colors hover:bg-indigo-100 dark:border-indigo-700 dark:bg-indigo-950/70 dark:text-indigo-200 dark:hover:bg-indigo-900/80"
                      >
                        <span>
                          Ir a {sn.id} · {sn.title}
                        </span>
                        <ArrowRight size={12} className="shrink-0" />
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
          {busy && (
            <div className="mr-6 inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-800/60">
              <Loader2 size={13} className="animate-spin" />
              Pensando respuesta socrática...
            </div>
          )}
          {err && <p className="text-xs text-rose-600 dark:text-rose-400">{err}</p>}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={send} className="flex items-center gap-2 border-t border-slate-200 p-3 dark:border-slate-800">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Escribe tu duda sobre este nodo o ramo..."
            className="min-w-0 flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 dark:border-slate-700 dark:bg-slate-950"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            aria-label="Enviar"
            className="inline-flex shrink-0 items-center justify-center rounded-md bg-slate-900 p-2 text-white hover:bg-slate-700 disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
          >
            <Send size={16} />
          </button>
        </form>
      </aside>
    </div>
  )
}
