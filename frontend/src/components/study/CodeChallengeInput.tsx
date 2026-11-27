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

export function getLanguageExtension(language?: CodeLanguage | string | null) {
  const normalized = (language ?? 'java').toLowerCase()
  if (normalized === 'sql') return [sql()]
  if (normalized === 'python') return [python()]
  if (normalized === 'c' || normalized === 'cpp' || normalized === 'c++') return [cpp()]
  if (normalized === 'java') return [java()]
  return []
}

function isPlaceholderComment(code: string): boolean {
  const s = code.trim()
  if (!s) return true
  const lines = s
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  if (lines.length !== 1) return false
  const ln = lines[0]
  return (
    ln.startsWith('//') ||
    ln.startsWith('--') ||
    ln.startsWith('#') ||
    (ln.startsWith('/*') && ln.endsWith('*/'))
  )
}

function expandSingleLineBraceCode(rawCode: string): string {
  let indent = 0
  const outLines: string[] = []
  let buf = ''
  let parenDepth = 0
  let inStr: string | null = null
  let escape = false

  const flushLine = () => {
    const line = buf.replace(/[ \t]+/g, ' ').trim()
    buf = ''
    if (line) {
      outLines.push('    '.repeat(indent) + line)
    }
  }

  for (let i = 0; i < rawCode.length; i++) {
    const ch = rawCode[i]
    if (inStr !== null) {
      buf += ch
      if (escape) {
        escape = false
      } else if (ch === '\\') {
        escape = true
      } else if (ch === inStr) {
        inStr = null
      }
      continue
    }
    if (ch === '"' || ch === "'") {
      inStr = ch
      buf += ch
      continue
    }
    if (ch === '/' && rawCode[i + 1] === '*') {
      const endComment = rawCode.indexOf('*/', i + 2)
      if (endComment === -1) {
        buf += rawCode.slice(i)
        break
      }
      if (buf.trim()) flushLine()
      buf = rawCode.slice(i, endComment + 2)
      flushLine()
      i = endComment + 1
      continue
    }
    if (ch === '/' && rawCode[i + 1] === '/') {
      const endLn = rawCode.indexOf('\n', i + 2)
      if (buf.trim()) flushLine()
      if (endLn === -1) {
        buf = rawCode.slice(i)
        flushLine()
        break
      }
      buf = rawCode.slice(i, endLn)
      flushLine()
      i = endLn
      continue
    }
    if (ch === '(') {
      parenDepth += 1
      buf += ch
    } else if (ch === ')') {
      parenDepth = Math.max(0, parenDepth - 1)
      buf += ch
    } else if (ch === '{' && parenDepth === 0) {
      const cur = buf.trimEnd()
      buf = cur ? `${cur} {` : '{'
      flushLine()
      indent += 1
    } else if (ch === '}' && parenDepth === 0) {
      flushLine()
      indent = Math.max(0, indent - 1)
      let j = i + 1
      while (j < rawCode.length && (rawCode[j] === ' ' || rawCode[j] === '\t')) j++
      if (j < rawCode.length && rawCode[j] === ';') {
        outLines.push('    '.repeat(indent) + '};')
        i = j
        continue
      }
      outLines.push('    '.repeat(indent) + '}')
    } else if (ch === ';' && parenDepth === 0) {
      buf += ';'
      flushLine()
    } else if (ch === '\n') {
      flushLine()
    } else {
      buf += ch
    }
  }
  flushLine()
  return outLines.join('\n')
}

export function formatMultilineStarterCode(
  starterCode?: string | null,
  language?: CodeLanguage | string | null,
): string {
  const cleaned = (starterCode ?? '').trim()
  if (!cleaned || isPlaceholderComment(cleaned)) return cleaned

  const lang = (language ?? 'java').toLowerCase()
  const rawLines = cleaned
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
  const nonCommentLines = rawLines.filter(
    (l) =>
      !l.startsWith('//') &&
      !l.startsWith('--') &&
      !l.startsWith('#') &&
      !(l.startsWith('/*') && l.endsWith('*/')),
  )

  if (lang === 'sql' || (!cleaned.includes('{') && /\bSELECT\b[\s\S]+\bFROM\b/i.test(cleaned))) {
    if (nonCommentLines.length <= 1) {
      return cleaned
        .replace(
          /\s+\b((?:INNER|LEFT|RIGHT|FULL)\s+JOIN|JOIN|FROM|WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT|VALUES|SET)\b/gi,
          '\n$1',
        )
        .trim()
    }
    return cleaned
  }

  let needsBraceExpand =
    nonCommentLines.length <= 1 &&
    (cleaned.includes('{') || (cleaned.match(/;/g)?.length ?? 0) >= 2)
  if (!needsBraceExpand && nonCommentLines.length <= 2) {
    needsBraceExpand = nonCommentLines.some(
      (l) => l.includes('{') && l.includes('}') && l.includes(';'),
    )
  }

  if (needsBraceExpand) {
    return expandSingleLineBraceCode(cleaned)
  }
  return cleaned
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function sanitizeCodePrompt(
  question: string,
  starterCode?: string | null,
  language?: CodeLanguage | string | null,
): { question: string; starterCode: string } {
  const qOrig = (question ?? '').trim()
  const rawStarter = (starterCode ?? '').trim()
  const formattedStarter = formatMultilineStarterCode(rawStarter, language)

  if (!rawStarter || isPlaceholderComment(rawStarter)) {
    return { question: qOrig, starterCode: formattedStarter }
  }

  let qClean = qOrig.replace(/```[\s\S]*?```/g, ' ')

  const strippedComments = rawStarter
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .split('\n')
    .map((l) => l.replace(/\/\/.*$/, '').trim())
    .filter((l) => l && !l.startsWith('--') && !l.startsWith('#'))
    .join('\n')

  const candidates = [rawStarter, formattedStarter, strippedComments].filter(Boolean)
  for (const cand of candidates) {
    const tokens = cand.trim().split(/\s+/).filter(Boolean)
    if (tokens.length >= 3) {
      const pat = new RegExp(
        `[:\\s]*\`?${tokens.map(escapeRegExp).join('\\s+')}\`?`,
        'gi',
      )
      qClean = qClean.replace(pat, ' ')
    }
  }

  qClean = qClean.replace(
    /[:\n]\s*`?(?:import\s+[\w.]+;\s*)*(?:(?:public|private|protected|static|final|abstract)\s+)*(?:class|interface|void|int|double|float|long|boolean|String|List|Map|Set)\b[\s\S]*\{[\s\S]*\}[\s;]*`?\s*$/,
    '.',
  )
  qClean = qClean.replace(/[:\n]\s*`?SELECT\s+[\s\S]+\s+FROM\s+[\s\S]+;?\s*`?\s*$/i, '.')

  qClean = qClean
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{2,}/g, '\n')
    .trim()
    .replace(/\s*:\s*$/, '.')
    .replace(/\.{2,}$/, '.')
    .trim()

  if (qClean.length < 10) {
    qClean =
      'Analiza el código del editor, identifica el problema técnico y resuélvelo según los criterios del nodo.'
  }

  return { question: qClean, starterCode: formattedStarter }
}

export default function CodeChallengeInput({ prompt, index, value, onChange }: Props) {
  const theme = useAppStore((s) => s.theme)
  const challengeType: ChallengeType = (prompt.challenge_type ?? 'concept') as ChallengeType
  const { question: cleanQuestion, starterCode } = useMemo(
    () => sanitizeCodePrompt(prompt.question, prompt.starter_code, prompt.language),
    [prompt.question, prompt.starter_code, prompt.language],
  )
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
          {index + 1}. {cleanQuestion}
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
          {index + 1}. {cleanQuestion}
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
        {index + 1}. {cleanQuestion}
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
