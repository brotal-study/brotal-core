import { useEffect, useRef, useState } from 'react'
import { Info, Loader2, MessageSquare, Send, Trash2, X } from 'lucide-react'
import {
  clearChatHistory,
  getChatHistory,
  sendChatMessage,
  type ChatMessage,
} from '../../api/study'

interface Props {
  open: boolean
  onClose: () => void
  courseId: string
  courseTitle: string
  nodeId: string | null
  nodeTitle: string | null
  initialPrompt?: string | null
  contextBanner?: string | null
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
}: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [provider, setProvider] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open || !courseId) return
    setErr(null)
    void getChatHistory(courseId)
      .then((hist) => setMessages(hist))
      .catch(() => setErr('No se pudo cargar el historial del tutor.'))
  }, [open, courseId])

  useEffect(() => {
    if (open && initialPrompt) {
      setInput(initialPrompt)
      setTimeout(() => inputRef.current?.focus(), 60)
    }
  }, [open, initialPrompt])

  useEffect(() => {
    if (open) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, open])

  if (!open) return null

  const send = async (e: React.FormEvent) => {
    e.preventDefault()
    const text = input.trim()
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
      setProvider(res.provider)
    } catch {
      setErr('No se pudo enviar el mensaje al tutor.')
      setInput(text)
    } finally {
      setBusy(false)
    }
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
        className="flex h-full w-full max-w-md flex-col border-l border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900"
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
          {messages.map((m) => (
            <div
              key={m.id}
              className={`flex flex-col rounded-lg px-3 py-2 text-sm ${
                m.role === 'user'
                  ? 'ml-8 bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                  : 'mr-6 border border-slate-200 bg-slate-50 text-slate-800 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-100'
              }`}
            >
              <div className="whitespace-pre-wrap break-words leading-relaxed">{m.content}</div>
            </div>
          ))}
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
