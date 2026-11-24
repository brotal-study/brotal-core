import { Gauge, Pause, Play, Square, Swords, Volume2 } from 'lucide-react'
import type { PackNode } from '../../api/study'
import { useSpeech } from './useSpeech'

interface Props {
  node: PackNode
  worldMetaphor: string | null
  onEvaluate: () => void
}

export default function StoryTab({ node, worldMetaphor, onEvaluate }: Props) {
  const speech = useSpeech(node.story_script)
  const paragraphs = node.story_script.split(/\n{2,}/).filter(Boolean)

  return (
    <div className="flex flex-col gap-4">
      {worldMetaphor && (
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800/60">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Mundo</span>
          <div className="font-medium">{worldMetaphor}</div>
        </div>
      )}

      <p className="text-sm text-slate-600 dark:text-slate-300">{node.summary}</p>

      <div className="flex flex-wrap items-center gap-2 rounded-md border border-slate-200 p-2 dark:border-slate-700">
        <Volume2 size={16} className="text-slate-500" />
        {!speech.supported ? (
          <span className="text-xs text-slate-500">Tu navegador no soporta audio de voz.</span>
        ) : (
          <>
            {speech.state === 'playing' ? (
              <button type="button" onClick={speech.pause} className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800">
                <Pause size={14} /> Pausar
              </button>
            ) : (
              <button type="button" onClick={speech.play} className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800">
                <Play size={14} /> {speech.state === 'paused' ? 'Continuar' : 'Escuchar'}
              </button>
            )}
            <button type="button" onClick={speech.stop} disabled={speech.state === 'idle'} className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:hover:bg-slate-800">
              <Square size={14} /> Detener
            </button>
            <label className="ml-auto inline-flex items-center gap-1 text-xs text-slate-600 dark:text-slate-300">
              <Gauge size={14} />
              <select
                value={speech.rate}
                onChange={(e) => speech.setRate(Number(e.target.value))}
                aria-label="Velocidad"
                className="rounded border border-slate-300 bg-transparent px-1 py-0.5 dark:border-slate-600"
              >
                {[0.75, 1, 1.25, 1.5].map((r) => (
                  <option key={r} value={r} className="text-slate-900">
                    {r}x
                  </option>
                ))}
              </select>
            </label>
            <span className="w-full text-[11px] text-slate-500 dark:text-slate-400">
              Voz del navegador (v0.1) — en v1.0 usará audio edge-tts en caché.
            </span>
          </>
        )}
      </div>

      <article className="flex flex-col gap-3 text-[15px] leading-relaxed">
        {paragraphs.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </article>

      <button
        type="button"
        onClick={onEvaluate}
        className="inline-flex items-center justify-center gap-2 self-start rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
      >
        <Swords size={16} /> Evaluarme a ciegas
      </button>
    </div>
  )
}
