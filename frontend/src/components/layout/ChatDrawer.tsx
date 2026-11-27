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
  const [expanded, setExpanded] = useState(false)
  const [provider, setProvider] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const lastAutoSentTriggerRef = useRef(0)

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
        className={`flex h-full w-full flex-col border-l border-slate-200 bg-white shadow-xl transition-[max-width] duration-200 dark:border-slate-800 dark:bg-slate-900 ${
          expanded ? 'max-w-3xl' : 'max-w-md'
        }`}
      >
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
              onClick={() => setExpanded((v) => !v)}
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
