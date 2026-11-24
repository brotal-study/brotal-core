import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowRight } from 'lucide-react'

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
            const isBlock = Boolean(codeClass && codeClass.includes('language-'))
            if (isBlock) {
              return (
                <code className="block overflow-x-auto rounded-md bg-slate-900 p-2.5 font-mono text-xs text-slate-100 dark:bg-slate-950">
                  {children}
                </code>
              )
            }
            return (
              <code className="rounded bg-slate-200/80 px-1 py-0.5 font-mono text-xs text-slate-900 dark:bg-slate-700/80 dark:text-slate-100">
                {children}
              </code>
            )
          },
          pre: ({ children }) => (
            <pre className="my-2 overflow-x-auto rounded-md bg-slate-900 p-2.5 font-mono text-xs text-slate-100 dark:bg-slate-950">
              {children}
            </pre>
          ),
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
