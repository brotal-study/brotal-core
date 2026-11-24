import { useEffect, useMemo, useRef, useState } from 'react'
import {
  FastForward,
  Gauge,
  Loader2,
  MessageSquare,
  Pause,
  Play,
  RefreshCw,
  Rewind,
  Square,
  Swords,
  Volume2,
} from 'lucide-react'
import {
  fetchNodeTtsBlob,
  fetchNodeTtsTimings,
  type PackNode,
  type TtsSentenceTiming,
} from '../../api/study'
import { splitStoryParagraphSentences, useSpeech } from './useSpeech'

interface Props {
  courseId: string
  node: PackNode
  worldMetaphor: string | null
  onEvaluate: () => void
  onRegenerateStory: () => Promise<void>
  onAskTutor: (ctx: { prompt: string; banner: string }) => void
}

function formatTime(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '0:00'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s < 10 ? '0' : ''}${s}`
}

function buildSentenceWindows(
  sentences: { text: string }[],
  serverTimings: TtsSentenceTiming[],
  audioDuration: number,
): { start: number; end: number }[] {
  if (sentences.length === 0) return []

  if (serverTimings.length === sentences.length) {
    return serverTimings.map((t, idx) => {
      const nextStart = idx < serverTimings.length - 1 ? serverTimings[idx + 1].start : undefined
      const endVal = nextStart !== undefined ? Math.max(t.end, nextStart) : Math.max(t.end, audioDuration || t.end)
      return { start: t.start, end: endVal }
    })
  }

  const lastTimingEnd = serverTimings.length > 0 ? serverTimings[serverTimings.length - 1].end : 0
  const totalDuration = audioDuration > 0 ? audioDuration : lastTimingEnd
  if (totalDuration <= 0) {
    return sentences.map((_, i) => ({ start: i * 3, end: (i + 1) * 3 }))
  }

  const lengths = sentences.map((s) => Math.max(1, s.text.length))
  const totalChars = lengths.reduce((acc, n) => acc + n, 0)
  let accChars = 0

  return lengths.map((len, idx) => {
    const start = (accChars / totalChars) * totalDuration
    accChars += len
    const end = idx === lengths.length - 1 ? totalDuration : (accChars / totalChars) * totalDuration
    return {
      start: Math.round(start * 1000) / 1000,
      end: Math.round(end * 1000) / 1000,
    }
  })
}

export default function StoryTab({
  courseId,
  node,
  worldMetaphor,
  onEvaluate,
  onRegenerateStory,
  onAskTutor,
}: Props) {
  const speech = useSpeech(node.story_script)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const blobUrlRef = useRef<string | null>(null)
  const sentenceRefs = useRef<Record<number, HTMLSpanElement | null>>({})
  const lastManualScrollRef = useRef<number>(0)

  const [mode, setMode] = useState<'neural' | 'fallback'>('neural')
  const [loadingAudio, setLoadingAudio] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState(1.0)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [serverTimings, setServerTimings] = useState<TtsSentenceTiming[]>([])
  const [regenerating, setRegenerating] = useState(false)

  const { paragraphs: structuredParagraphs, flat: flatSentences } = useMemo(
    () => splitStoryParagraphSentences(node.story_script),
    [node.story_script],
  )

  const sentenceWindows = useMemo(
    () => buildSentenceWindows(flatSentences, serverTimings, duration),
    [flatSentences, serverTimings, duration],
  )

  // Detectar scroll manual del usuario para no secuestrar el scroll durante auto-seguimiento
  useEffect(() => {
    const markManualScroll = () => {
      lastManualScrollRef.current = Date.now()
    }
    window.addEventListener('wheel', markManualScroll, { passive: true })
    window.addEventListener('touchmove', markManualScroll, { passive: true })
    return () => {
      window.removeEventListener('wheel', markManualScroll)
      window.removeEventListener('touchmove', markManualScroll)
    }
  }, [])

  // Limpiar audio al cambiar de nodo o de story_script
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current)
      blobUrlRef.current = null
    }
    setPlaying(false)
    setCurrentTime(0)
    setDuration(0)
    setServerTimings([])
    setMode('neural')
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current = null
      }
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current)
        blobUrlRef.current = null
      }
    }
  }, [courseId, node.id, node.story_script])

  const loadNeuralAudio = async (seekToSentenceIdx?: number) => {
    setLoadingAudio(true)
    try {
      const blob = await fetchNodeTtsBlob(courseId, node.id)
      const fetchedTimings = await fetchNodeTtsTimings(courseId, node.id)
      setServerTimings(fetchedTimings)

      const url = URL.createObjectURL(blob)
      blobUrlRef.current = url
      const audio = new Audio(url)
      audio.playbackRate = rate
      audio.addEventListener('timeupdate', () => setCurrentTime(audio.currentTime))
      audio.addEventListener('loadedmetadata', () => {
        const dur = audio.duration || 0
        setDuration(dur)
        if (seekToSentenceIdx !== undefined) {
          const wins = buildSentenceWindows(flatSentences, fetchedTimings, dur)
          const target = wins[seekToSentenceIdx]?.start ?? 0
          audio.currentTime = target
          setCurrentTime(target)
        }
      })
      audio.addEventListener('play', () => setPlaying(true))
      audio.addEventListener('pause', () => setPlaying(false))
      audio.addEventListener('ended', () => {
        setPlaying(false)
        setCurrentTime(0)
      })
      audioRef.current = audio
      await audio.play()
    } catch {
      // Fallback offline a speechSynthesis del navegador
      setMode('fallback')
      speech.setRate(rate)
      if (seekToSentenceIdx !== undefined) {
        speech.playFromSentence(seekToSentenceIdx)
      } else {
        speech.play()
      }
    } finally {
      setLoadingAudio(false)
    }
  }

  const togglePlay = async () => {
    if (mode === 'fallback') {
      if (speech.state === 'playing') speech.pause()
      else speech.play()
      return
    }

    if (audioRef.current) {
      if (playing) {
        audioRef.current.pause()
      } else {
        await audioRef.current.play()
      }
      return
    }

    await loadNeuralAudio()
  }

  const handleSentenceClick = async (sentenceIdx: number) => {
    if (mode === 'fallback') {
      speech.playFromSentence(sentenceIdx)
      return
    }

    if (audioRef.current) {
      const targetStart = sentenceWindows[sentenceIdx]?.start ?? 0
      audioRef.current.currentTime = targetStart
      setCurrentTime(targetStart)
      if (!playing) {
        await audioRef.current.play()
      }
      return
    }

    await loadNeuralAudio(sentenceIdx)
  }

  const stopAudio = () => {
    if (mode === 'fallback') {
      speech.stop()
      return
    }
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
      setCurrentTime(0)
      setPlaying(false)
    }
  }

  const seekBy = (delta: number) => {
    if (!audioRef.current) return
    const next = Math.max(0, Math.min(duration || Infinity, audioRef.current.currentTime + delta))
    audioRef.current.currentTime = next
    setCurrentTime(next)
  }

  const onSeekSlider = (val: number) => {
    if (!audioRef.current) return
    audioRef.current.currentTime = val
    setCurrentTime(val)
  }

  const changeRate = (nextRate: number) => {
    setRate(nextRate)
    speech.setRate(nextRate)
    if (audioRef.current) {
      audioRef.current.playbackRate = nextRate
    }
  }

  const handleRegenerate = async () => {
    stopAudio()
    setRegenerating(true)
    try {
      await onRegenerateStory()
    } finally {
      setRegenerating(false)
    }
  }

  const isPlaying = mode === 'fallback' ? speech.state === 'playing' : playing

  const activeSentenceIndex = useMemo(() => {
    if (mode === 'fallback') {
      return speech.activeSentenceIndex
    }
    if (!playing && currentTime <= 0) return null
    if (sentenceWindows.length === 0) return null
    for (let i = 0; i < sentenceWindows.length; i++) {
      const w = sentenceWindows[i]
      if (currentTime >= w.start && currentTime < w.end) {
        return i
      }
    }
    if (currentTime >= sentenceWindows[sentenceWindows.length - 1].start) {
      return sentenceWindows.length - 1
    }
    return 0
  }, [currentTime, mode, playing, sentenceWindows, speech.activeSentenceIndex])

  // Auto-scroll suave a la oracion activa sin secuestrar el scroll manual
  useEffect(() => {
    if (!isPlaying || activeSentenceIndex === null) return
    if (Date.now() - lastManualScrollRef.current < 2500) return
    const el = sentenceRefs.current[activeSentenceIndex]
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [activeSentenceIndex, isPlaying])

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-4">
      {worldMetaphor && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800/60">
          <div className="min-w-0 flex-1">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Mundo
            </span>
            <div className="break-words font-medium">{worldMetaphor}</div>
          </div>
          <button
            type="button"
            disabled={regenerating}
            onClick={handleRegenerate}
            title="Genera otra explicación conversada manteniendo la metáfora del ramo"
            className="inline-flex shrink-0 items-center gap-1.5 rounded border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-900 dark:hover:bg-slate-800"
          >
            <RefreshCw size={13} className={regenerating ? 'animate-spin' : ''} />
            {regenerating ? 'Re-explicando...' : 'Otra explicación'}
          </button>
        </div>
      )}

      {!worldMetaphor && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="min-w-0 flex-1 break-words text-sm text-slate-600 dark:text-slate-300">
            {node.summary}
          </p>
          <button
            type="button"
            disabled={regenerating}
            onClick={handleRegenerate}
            className="inline-flex shrink-0 items-center gap-1.5 rounded border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800"
          >
            <RefreshCw size={13} className={regenerating ? 'animate-spin' : ''} />
            {regenerating ? 'Re-explicando...' : 'Otra explicación'}
          </button>
        </div>
      )}

      {worldMetaphor && (
        <p className="break-words text-sm text-slate-600 dark:text-slate-300">{node.summary}</p>
      )}

      {regenerating && (
        <div
          role="status"
          className="flex items-center gap-2 rounded-md border border-indigo-200 bg-indigo-50/70 px-3 py-2 text-xs text-indigo-950 dark:border-indigo-800/70 dark:bg-indigo-950/40 dark:text-indigo-200"
        >
          <Loader2 size={14} className=" shrink-0 animate-spin text-indigo-600 dark:text-indigo-400" />
          <span>
            Redactando otra explicación conversada (~200 palabras) con nuevo enfoque sobre la metáfora del ramo...
          </span>
        </div>
      )}

      <div className="flex flex-col gap-2 rounded-md border border-slate-200 p-2.5 dark:border-slate-700">
        <div className="flex flex-wrap items-center gap-2">
          <Volume2 size={16} className="text-slate-500" />
          <button
            type="button"
            disabled={loadingAudio}
            onClick={togglePlay}
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800"
          >
            {loadingAudio ? (
              <Loader2 size={14} className="animate-spin" />
            ) : isPlaying ? (
              <Pause size={14} />
            ) : (
              <Play size={14} />
            )}
            {loadingAudio ? 'Sintetizando voz...' : isPlaying ? 'Pausar' : 'Escuchar'}
          </button>
          <button
            type="button"
            onClick={stopAudio}
            disabled={!isPlaying && currentTime === 0}
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:hover:bg-slate-800"
          >
            <Square size={14} /> Detener
          </button>
          {mode === 'neural' && (
            <>
              <button
                type="button"
                onClick={() => seekBy(-5)}
                disabled={!audioRef.current}
                title="Retroceder 5 segundos"
                className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:hover:bg-slate-800"
              >
                <Rewind size={13} /> -5s
              </button>
              <button
                type="button"
                onClick={() => seekBy(5)}
                disabled={!audioRef.current}
                title="Adelantar 5 segundos"
                className="inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:hover:bg-slate-800"
              >
                <FastForward size={13} /> +5s
              </button>
            </>
          )}
          <label className="ml-auto inline-flex items-center gap-1 text-xs text-slate-600 dark:text-slate-300">
            <Gauge size={14} />
            <select
              value={rate}
              onChange={(e) => changeRate(Number(e.target.value))}
              aria-label="Velocidad"
              className="rounded border border-slate-300 bg-transparent px-1 py-0.5 dark:border-slate-600"
            >
              {[1.0, 1.25, 1.5].map((r) => (
                <option key={r} value={r} className="text-slate-900">
                  {r}x
                </option>
              ))}
            </select>
          </label>
        </div>

        {loadingAudio && (
          <div
            role="status"
            className="flex items-center gap-2 rounded bg-slate-100 px-2.5 py-1.5 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200"
          >
            <Loader2 size={13} className="shrink-0 animate-spin" />
            <span>Generando audio neural en español con edge-tts y guardando en caché local...</span>
          </div>
        )}

        {mode === 'neural' && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="w-9 font-mono text-[11px]">{formatTime(currentTime)}</span>
            <input
              type="range"
              min={0}
              max={duration > 0 ? duration : 100}
              step={0.5}
              value={currentTime}
              disabled={!audioRef.current || duration === 0}
              onChange={(e) => onSeekSlider(Number(e.target.value))}
              aria-label="Barra de progreso de audio"
              className="h-1.5 flex-1 cursor-pointer accent-slate-900 dark:accent-slate-100"
            />
            <span className="w-9 text-right font-mono text-[11px]">{formatTime(duration)}</span>
          </div>
        )}

        <span className="text-[11px] text-slate-500 dark:text-slate-400">
          {mode === 'neural'
            ? 'Voz neural edge-tts en español · Haz clic en cualquier oración para saltar en el audio.'
            : 'Fallback offline: síntesis de voz local del navegador · Haz clic en cualquier oración para escucharla.'}
        </span>
      </div>

      <article className="flex min-w-0 flex-col gap-3 break-words text-[15px] leading-relaxed">
        {structuredParagraphs.map((pSentences, pIdx) => (
          <p key={pIdx} className="break-words">
            {pSentences.map((s, sIdx) => {
              const isActive = activeSentenceIndex === s.globalIndex
              return (
                <span key={s.globalIndex}>
                  <span
                    ref={(el) => {
                      sentenceRefs.current[s.globalIndex] = el
                    }}
                    role="button"
                    tabIndex={0}
                    title="Clic para saltar a esta oración en el audio"
                    onClick={() => void handleSentenceClick(s.globalIndex)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        void handleSentenceClick(s.globalIndex)
                      }
                    }}
                    className={`cursor-pointer rounded px-1 py-0.5 transition-colors ${
                      isActive
                        ? 'bg-amber-100/95 font-medium text-slate-950 ring-1 ring-amber-300/90 dark:bg-indigo-950/90 dark:text-indigo-100 dark:ring-indigo-600/80'
                        : 'hover:bg-slate-100 dark:hover:bg-slate-800/70'
                    }`}
                  >
                    {s.text}
                  </span>
                  {sIdx < pSentences.length - 1 ? ' ' : ''}
                </span>
              )
            })}
          </p>
        ))}
      </article>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          type="button"
          onClick={onEvaluate}
          className="inline-flex items-center justify-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
        >
          <Swords size={16} /> Evaluarme a ciegas
        </button>
        <button
          type="button"
          onClick={() =>
            onAskTutor({
              prompt: `Tengo una duda sobre la explicación de "${node.title}": `,
              banner: `Consultando sobre la historia del nodo "${node.title}" (${node.block}).`,
            })
          }
          className="inline-flex items-center justify-center gap-1.5 rounded-md border border-slate-300 px-3.5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <MessageSquare size={15} /> Tengo una duda sobre esta historia
        </button>
      </div>
    </div>
  )
}
