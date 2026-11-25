import { useMemo } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { java } from '@codemirror/lang-java'
import { sql } from '@codemirror/lang-sql'
import { python } from '@codemirror/lang-python'
import { cpp } from '@codemirror/lang-cpp'
import { oneDark } from '@codemirror/theme-one-dark'
import { Bug, Code2, RotateCcw, Terminal } from 'lucide-react'
import type { ChallengeType, CodeLanguage, EvalPrompt } from '../../api/study'
import { useAppStore } from '../../store/useAppStore'

interface Props {
  prompt: EvalPrompt
  index: number
  value: string
  onChange: (nextValue: string) => void
}

function getLanguageExtension(language?: CodeLanguage | string | null) {
  const normalized = (language ?? 'java').toLowerCase()
  if (normalized === 'sql') return [sql()]
  if (normalized === 'python') return [python()]
  if (normalized === 'c' || normalized === 'cpp' || normalized === 'c++') return [cpp()]
  if (normalized === 'java') return [java()]
  return []
}

export default function CodeChallengeInput({ prompt, index, value, onChange }: Props) {
  const theme = useAppStore((s) => s.theme)
  const challengeType: ChallengeType = (prompt.challenge_type ?? 'concept') as ChallengeType
  const starterCode = prompt.starter_code ?? ''
  const langLabel = (prompt.language && prompt.language !== 'text' ? prompt.language : 'java').toUpperCase()

  const extensions = useMemo(() => getLanguageExtension(prompt.language), [prompt.language])
  const cmTheme = theme === 'dark' ? oneDark : 'light'

  if (challengeType === 'debug' || challengeType === 'implement') {
    const isDebug = challengeType === 'debug'
    const currentCode = value !== undefined ? value : starterCode
    const isModified = currentCode.trim() !== starterCode.trim()

    return (
      <div className="flex min-w-0 flex-col gap-2 rounded-md border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900/60">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span
              className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold ${
                isDebug
                  ? 'border border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700/80 dark:bg-amber-950/50 dark:text-amber-200'
                  : 'border border-indigo-300 bg-indigo-50 text-indigo-900 dark:border-indigo-700/80 dark:bg-indigo-950/50 dark:text-indigo-200'
              }`}
            >
              {isDebug ? <Bug size={12} /> : <Code2 size={12} />}
              {isDebug ? 'Corregir bug' : 'Implementar'}
            </span>
            <span className="rounded border border-slate-300 bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {langLabel}
            </span>
            {starterCode && (
              <span
                className={`text-[11px] font-medium ${
                  isModified
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-slate-500 dark:text-slate-400'
                }`}
              >
                {isModified ? 'Código editado' : 'Edita el código para responder'}
              </span>
            )}
          </div>

          {starterCode && (
            <button
              type="button"
              onClick={() => onChange(starterCode)}
              disabled={!isModified}
              className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <RotateCcw size={11} />
              Restaurar código inicial
            </button>
          )}
        </div>

        <span className="break-words text-sm font-medium">
          {index + 1}. {prompt.question}
        </span>

        <div className="overflow-hidden rounded-md border border-slate-300 text-xs dark:border-slate-700">
          <CodeMirror
            value={currentCode}
            height="210px"
            theme={cmTheme}
            extensions={extensions}
            onChange={(val) => onChange(val)}
            basicSetup={{
              lineNumbers: true,
              foldGutter: false,
              highlightActiveLine: true,
              autocompletion: true,
            }}
          />
        </div>
      </div>
    )
  }

  if (challengeType === 'trace') {
    return (
      <div className="flex min-w-0 flex-col gap-2 rounded-md border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900/60">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="inline-flex items-center gap-1 rounded border border-sky-300 bg-sky-50 px-2 py-0.5 text-[11px] font-semibold text-sky-900 dark:border-sky-700/80 dark:bg-sky-950/50 dark:text-sky-200">
            <Terminal size={12} />
            Traza de código
          </span>
          <span className="rounded border border-slate-300 bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {langLabel}
          </span>
        </div>

        <span className="break-words text-sm font-medium">
          {index + 1}. {prompt.question}
        </span>

        {starterCode && (
          <div className="overflow-hidden rounded-md border border-slate-300 text-xs dark:border-slate-700">
            <CodeMirror
              value={starterCode}
              editable={false}
              readOnly={true}
              theme={cmTheme}
              extensions={extensions}
              basicSetup={{
                lineNumbers: true,
                foldGutter: false,
                highlightActiveLine: false,
              }}
            />
          </div>
        )}

        <label className="flex min-w-0 flex-col gap-1">
          <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
            Salida exacta y explicación paso a paso de la traza:
          </span>
          <textarea
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value)}
            rows={4}
            className="w-full rounded-md border border-slate-300 bg-white p-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 dark:border-slate-600 dark:bg-slate-900"
            placeholder="Escribe qué imprime/retorna exactamente y explica la traza línea por línea..."
          />
        </label>
      </div>
    )
  }

  return (
    <label className="flex min-w-0 flex-col gap-1.5">
      <span className="break-words text-sm font-medium">
        {index + 1}. {prompt.question}
      </span>
      <textarea
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        rows={4}
        className="w-full rounded-md border border-slate-300 bg-white p-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 dark:border-slate-600 dark:bg-slate-900"
        placeholder="Tu respuesta..."
      />
    </label>
  )
}
