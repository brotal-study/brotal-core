import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Cpu, KeyRound, Server, ShieldCheck, User, X } from 'lucide-react'
import {
  getProvidersSettings,
  putProvidersSettings,
  type ProvidersSettings,
} from '../../api/curriculum'

interface Props {
  open: boolean
  onClose: () => void
}

const PROVIDERS: {
  id: 'auto' | 'groq' | 'gemini' | 'ollama'
  label: string
  desc: string
}[] = [
  { id: 'auto', label: 'Automático (Pool gratuito)', desc: 'Rota entre Groq, Gemini Free y Ollama local' },
  { id: 'groq', label: 'Groq Cloud (Free Tier)', desc: 'llama-3.3-70b-versatile / gpt-oss-120b' },
  { id: 'gemini', label: 'Google Gemini Free', desc: 'gemini-2.5-flash (AI Studio)' },
  { id: 'ollama', label: 'Ollama 100% Local', desc: 'Modelos locales en http://127.0.0.1:11434' },
]

export default function AiSettingsModal({ open, onClose }: Props) {
  const [settings, setSettings] = useState<ProvidersSettings | null>(null)
  const [provider, setProvider] = useState<'auto' | 'groq' | 'gemini' | 'ollama'>('auto')
  const [groqKey, setGroqKey] = useState('')
  const [geminiKey, setGeminiKey] = useState('')
  const [ollamaUrl, setOllamaUrl] = useState('http://127.0.0.1:11434')
  const [ollamaModel, setOllamaModel] = useState('llama3.2')
  const [busy, setBusy] = useState(false)
  const [savedMsg, setSavedMsg] = useState<string | null>(null)
  const [errMsg, setErrMsg] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setSavedMsg(null)
    setErrMsg(null)
    setGroqKey('')
    setGeminiKey('')
    void getProvidersSettings()
      .then((res) => {
        setSettings(res)
        setProvider(res.ai_provider)
        setOllamaUrl(res.models.ollama_url || 'http://127.0.0.1:11434')
        setOllamaModel(res.models.ollama || 'llama3.2')
      })
      .catch(() => setErrMsg('No se pudo cargar la configuración de IA.'))
  }, [open])

  if (!open) return null

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setSavedMsg(null)
    setErrMsg(null)
    try {
      const payload: Record<string, string> = {
        ai_provider: provider,
        ollama_url: ollamaUrl.trim(),
        ollama_model: ollamaModel.trim() || 'llama3.2',
      }
      if (groqKey.trim()) payload.groq_api_key = groqKey.trim()
      if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim()

      const updated = await putProvidersSettings(payload)
      setSettings(updated)
      setGroqKey('')
      setGeminiKey('')
      setSavedMsg('Guardado en ~/.brotal/.env (permisos 0600).')
    } catch {
      setErrMsg('No se pudo guardar la configuración.')
    } finally {
      setBusy(false)
    }
  }

  const clearKey = async (which: 'groq_api_key' | 'gemini_api_key') => {
    setBusy(true)
    try {
      const updated = await putProvidersSettings({ [which]: '' })
      setSettings(updated)
      setSavedMsg('Clave eliminada de ~/.brotal/.env.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-label="Configuración de IA"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-y-auto rounded-lg border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-800 dark:bg-slate-900"
      >
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 pb-3 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <Cpu size={18} className="text-slate-600 dark:text-slate-300" />
            <div>
              <h2 className="text-base font-semibold">Configuración de IA (BYOK · Costo $0)</h2>
              <p className="text-xs text-slate-500">
                Claves guardadas fuera del repositorio en <code className="font-mono">~/.brotal/.env</code> (0600).
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

        <form onSubmit={save} className="mt-4 flex flex-col gap-4">
          {settings && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-800/60">
              <span className="inline-flex items-center gap-1.5 font-medium">
                <ShieldCheck size={14} className="text-emerald-600 dark:text-emerald-400" />
                Motor activo:{' '}
                <strong className="font-mono">
                  {settings.active_provider} ({settings.active_model})
                </strong>
              </span>
              <Link
                to="/onboarding"
                onClick={onClose}
                className="inline-flex items-center gap-1 text-slate-600 underline hover:text-slate-900 dark:text-slate-300 dark:hover:text-white"
              >
                <User size={12} /> Editar perfil / carrera
              </Link>
            </div>
          )}

          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">
              Modo de enrutamiento
            </label>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {PROVIDERS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setProvider(p.id)}
                  className={`flex flex-col items-start rounded-md border p-2.5 text-left text-xs ${
                    provider === p.id
                      ? 'border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900'
                      : 'border-slate-300 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800'
                  }`}
                >
                  <span className="font-semibold">{p.label}</span>
                  <span className={`mt-0.5 text-[11px] ${provider === p.id ? 'opacity-80' : 'text-slate-500'}`}>
                    {p.desc}
                  </span>
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-3 rounded-md border border-slate-200 p-3 dark:border-slate-800">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold">
                <KeyRound size={14} /> Groq API Key
              </span>
              {settings?.providers.groq ? (
                <span className="inline-flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400">
                  <Check size={13} /> Configurada
                  <button
                    type="button"
                    onClick={() => clearKey('groq_api_key')}
                    className="text-[11px] text-slate-500 underline hover:text-rose-600"
                  >
                    Borrar
                  </button>
                </span>
              ) : (
                <span className="text-xs text-slate-400">No configurada</span>
              )}
            </div>
            <input
              type="password"
              value={groqKey}
              onChange={(e) => setGroqKey(e.target.value)}
              placeholder={settings?.providers.groq ? '•••••••• (dejar vacío para conservar)' : 'gsk_...'}
              className="rounded border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
            />
          </div>

          <div className="flex flex-col gap-3 rounded-md border border-slate-200 p-3 dark:border-slate-800">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold">
                <KeyRound size={14} /> Gemini API Key (Google AI Studio)
              </span>
              {settings?.providers.gemini ? (
                <span className="inline-flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400">
                  <Check size={13} /> Configurada
                  <button
                    type="button"
                    onClick={() => clearKey('gemini_api_key')}
                    className="text-[11px] text-slate-500 underline hover:text-rose-600"
                  >
                    Borrar
                  </button>
                </span>
              ) : (
                <span className="text-xs text-slate-400">No configurada</span>
              )}
            </div>
            <input
              type="password"
              value={geminiKey}
              onChange={(e) => setGeminiKey(e.target.value)}
              placeholder={settings?.providers.gemini ? '•••••••• (dejar vacío para conservar)' : 'AIza...'}
              className="rounded border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
            />
          </div>

          <div className="flex flex-col gap-2 rounded-md border border-slate-200 p-3 dark:border-slate-800">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold">
                <Server size={14} /> Ollama Local
              </span>
              <span className="text-xs text-slate-500">
                {settings?.providers.ollama ? 'Activo' : 'Opcional'}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-slate-500">URL</span>
                <input
                  type="text"
                  value={ollamaUrl}
                  onChange={(e) => setOllamaUrl(e.target.value)}
                  placeholder="http://127.0.0.1:11434"
                  className="rounded border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs">
                <span className="text-slate-500">Modelo</span>
                <input
                  type="text"
                  value={ollamaModel}
                  onChange={(e) => setOllamaModel(e.target.value)}
                  placeholder="llama3.2"
                  className="rounded border border-slate-300 bg-white px-2.5 py-1.5 font-mono text-xs dark:border-slate-700 dark:bg-slate-950"
                />
              </label>
            </div>
          </div>

          {savedMsg && <p className="text-xs font-medium text-emerald-600 dark:text-emerald-400">{savedMsg}</p>}
          {errMsg && <p className="text-xs font-medium text-rose-600 dark:text-rose-400">{errMsg}</p>}

          <div className="flex justify-end gap-2 border-t border-slate-200 pt-3 dark:border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
            >
              Cerrar
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-slate-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
            >
              {busy ? 'Guardando...' : 'Guardar configuración'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
