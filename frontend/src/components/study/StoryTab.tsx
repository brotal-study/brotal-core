import { useEffect, useRef, useState } from 'react'
import {
  FastForward,
  Gauge,
  Pause,
  Play,
  RefreshCw,
  Rewind,
  Square,
  Swords,
  Volume2,
} from 'lucide-react'
import { fetchNodeTtsBlob, type PackNode } from '../../api/study'
import { useSpeech } from './useSpeech'

interface Props {
  courseId: string
  node: PackNode
  worldMetaphor: string | null
  onEvaluate: () => void
  onRegenerateStory: () => Promise<void>
}

function formatTime(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '0:00'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s < 10 ? '0' : ''}${s}`
}

export default function StoryTab({
  courseId,
  node,
  worldMetaphor,
  onEvaluate,
  onRegenerateStory,
}: Props) {
  const speech = useSpeech(node.story_script)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const blobUrlRef = useRef<string | null>(null)

  const [mode, setMode] = useState<'neural' | 'fallback'>('neural')
  const [loadingAudio, setLoadingAudio] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState(1.0)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [regenerating, setRegenerating] = useState(false)

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

    setLoadingAudio(true)
    try {
      const blob = await fetchNodeTtsBlob(courseId, node.id)
      const url = URL.createObjectURL(blob)
      blobUrlRef.current = url
      const audio = new Audio(url)
      audio.playbackRate = rate
      audio.addEventListener('timeupdate', () => setCurrentTime(audio.currentTime))
      audio.addEventListener('loadedmetadata', () => setDuration(audio.duration || 0))
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
      speech.play()
    } finally {
      setLoadingAudio(false)
    }
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

  const paragraphs = node.story_script.split(/\n{2,}/).filter(Boolean)
  const isPlaying = mode === 'fallback' ? speech.state === 'playing' : playing

  return (
    <div className="flex flex-col gap-4">
      {worldMetaphor && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800/60">
          <div>
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Mundo
            </span>
            <div className="font-medium">{worldMetaphor}</div>
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
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm text-slate-600 dark:text-slate-300">{node.summary}</p>
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

      {worldMetaphor && <p className="text-sm text-slate-600 dark:text-slate-300">{node.summary}</p>}

      <div className="flex flex-col gap-2 rounded-md border border-slate-200 p-2.5 dark:border-slate-700">
        <div className="flex flex-wrap items-center gap-2">
          <Volume2 size={16} className="text-slate-500" />
          <button
            type="button"
            disabled={loadingAudio}
            onClick={togglePlay}
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800"
          >
            {isPlaying ? <Pause size={14} /> : <Play size={14} />}
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
            ? 'Voz neural edge-tts en español (MP3 con caché local en ~/.brotal/tts_cache).'
            : 'Fallback offline: síntesis de voz local del navegador.'}
        </span>
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
