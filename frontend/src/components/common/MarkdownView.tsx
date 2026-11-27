import { isValidElement, useMemo, useState, type ReactNode } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { oneDark } from '@codemirror/theme-one-dark'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowRight, Check, Copy } from 'lucide-react'
import { useAppStore } from '../../store/useAppStore'
import { getLanguageExtension } from '../study/CodeChallengeInput'

interface Props {
  content: string
  onSelectNode?: (nodeId: string) => void
  className?: string
}

const NODE_TOKEN_RE = /\[\[node:([^|\]]+)\|([^\]]+)\]\]/g
const NODE_HREF_PREFIX = '#brotal-node-'

/**
 * Transforma menciones [[node:<ID>|<Titulo>]] en enlaces markdown internos
 * para que ReactMarkdown los renderice como botones clicables sin romper listas ni negritas.
 */
function preprocessNodeLinks(raw: string): string {
  return raw.replace(NODE_TOKEN_RE, (_match, rawId: string, rawTitle: string) => {
    const id = rawId.trim()
    const title = rawTitle.trim()
    return `[${id} · ${title}](${NODE_HREF_PREFIX}${encodeURIComponent(id)})`
  })
}

function inferCodeLanguage(rawLang: string | null, code: string): string {
  if (rawLang) {
    const low = rawLang.trim().toLowerCase()
    if (low === 'java' || low === 'sql' || low === 'python' || low === 'py' || low === 'c' || low === 'cpp' || low === 'c++') {
      return low === 'py' ? 'python' : low
    }
    return low
  }
  if (/\b(?:public\s+class|System\.out\.|@Override|try\s*\{|catch\s*\()\b/.test(code)) return 'java'
  if (/\b(?:SELECT\s+.+\s+FROM|CREATE\s+TABLE|GROUP\s+BY)\b/i.test(code)) return 'sql'
  if (/\b(?:def\s+\w+\(|import\s+\w+|elif\s+)\b/.test(code)) return 'python'
  return 'text'
}

function extractText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return extractText(node.props.children)
  }
  return ''
}

function MarkdownCodeBlock({ code, language }: { code: string; language: string | null }) {
  const theme = useAppStore((s) => s.theme)
  const [copied, setCopied] = useState(false)
  const cleanedCode = code.replace(/\n$/, '')
  const detectedLang = useMemo(
    () => inferCodeLanguage(language, cleanedCode),
    [language, cleanedCode],
  )
  const extensions = useMemo(
    () => (detectedLang === 'text' ? [] : getLanguageExtension(detectedLang)),
    [detectedLang],
  )
  const cmTheme = theme === 'dark' ? oneDark : 'light'
  const langLabel = detectedLang === 'text' ? 'CÓDIGO' : detectedLang.toUpperCase()

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(cleanedCode)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      // Clipboard no disponible en entorno restringido
    }
  }

  return (
    <div className="my-2 overflow-hidden rounded-md border border-slate-300 bg-white dark:border-slate-700 dark:bg-slate-950">
      <div className="flex items-center justify-between gap-2 border-b border-slate-200 bg-slate-100 px-2.5 py-1 text-[11px] text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
        <span className="font-mono font-semibold uppercase tracking-wide">{langLabel}</span>
        <button
          type="button"
          onClick={() => void handleCopy()}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium hover:bg-slate-200/80 dark:hover:bg-slate-800"
        >
          {copied ? (
            <>
              <Check size={12} className="text-emerald-600 dark:text-emerald-400" />
              Copiado
            </>
          ) : (
            <>
              <Copy size={12} />
              Copiar
            </>
          )}
        </button>
      </div>
      <div className="text-xs">
        <CodeMirror
          value={cleanedCode}
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
    </div>
  )
}

export default function MarkdownView({ content, onSelectNode, className = '' }: Props) {
  const prepared = preprocessNodeLinks(content)

  return (
    <div className={`min-w-0 max-w-full break-words text-sm leading-relaxed ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="mb-2 mt-3 text-base font-bold text-slate-900 first:mt-0 dark:text-slate-100">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="mb-1.5 mt-2.5 text-sm font-bold text-slate-900 first:mt-0 dark:text-slate-100">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="mb-1 mt-2 text-sm font-semibold text-slate-900 first:mt-0 dark:text-slate-100">
              {children}
            </h3>
          ),
          p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
          strong: ({ children }) => (
            <strong className="font-semibold text-slate-950 dark:text-white">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          ul: ({ children }) => (
            <ul className="mb-2 ml-4 list-disc space-y-1 last:mb-0">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="mb-2 ml-4 list-decimal space-y-1 last:mb-0">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-indigo-400 pl-3 italic text-slate-600 dark:border-indigo-500 dark:text-slate-300">
              {children}
            </blockquote>
          ),
          code: ({ className: codeClass, children }) => {
            const langMatch = codeClass?.match(/language-([a-zA-Z0-9+#_-]+)/)
            const rawText = extractText(children)
            if (langMatch || rawText.includes('\n')) {
              return <MarkdownCodeBlock code={rawText} language={langMatch?.[1] ?? null} />
            }
            return (
              <code className="rounded bg-slate-200/80 px-1 py-0.5 font-mono text-xs text-slate-900 dark:bg-slate-700/80 dark:text-slate-100">
                {children}
              </code>
            )
          },
          pre: ({ children }) => {
            if (isValidElement<{ className?: string; children?: ReactNode }>(children)) {
              const langMatch = children.props.className?.match(/language-([a-zA-Z0-9+#_-]+)/)
              const rawText = extractText(children.props.children)
              return <MarkdownCodeBlock code={rawText} language={langMatch?.[1] ?? null} />
            }
            return <MarkdownCodeBlock code={extractText(children)} language={null} />
          },
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse border border-slate-300 text-xs dark:border-slate-700">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-slate-300 bg-slate-100 px-2 py-1 text-left font-semibold dark:border-slate-700 dark:bg-slate-800">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border border-slate-300 px-2 py-1 dark:border-slate-700">{children}</td>
          ),
          a: ({ href, children }) => {
            if (href && href.startsWith(NODE_HREF_PREFIX)) {
              const nodeId = decodeURIComponent(href.slice(NODE_HREF_PREFIX.length))
              return (
                <button
                  type="button"
                  onClick={() => onSelectNode?.(nodeId)}
                  className="mx-0.5 my-0.5 inline-flex items-center gap-1 rounded-md border border-indigo-300 bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-900 transition-colors hover:bg-indigo-100 dark:border-indigo-700 dark:bg-indigo-950/70 dark:text-indigo-200 dark:hover:bg-indigo-900/80"
                >
                  <span>Ir a {children}</span>
                  <ArrowRight size={12} className="shrink-0" />
                </button>
              )
            }
            return (
              <a
                href={href}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-indigo-600 underline hover:text-indigo-800 dark:text-indigo-400 dark:hover:text-indigo-300"
              >
                {children}
              </a>
            )
          },
        }}
      >
        {prepared}
      </ReactMarkdown>
    </div>
  )
}
