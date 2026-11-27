import { useEffect, useMemo, useRef, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { oneDark } from '@codemirror/theme-one-dark'
import {
  Check,
  Code2,
  Copy,
  FastForward,
  Gauge,
  Languages,
  Loader2,
  MessageSquare,
  Pause,
  Play,
  RefreshCw,
  Rewind,
  Send,
  Square,
  Swords,
  Volume2,
} from 'lucide-react'
import type { ExplanationStyle } from '../../api/curriculum'
import {
  fetchNodeTtsBlob,
  fetchNodeTtsTimingsData,
  fetchPhraseTtsBlob,
  type PackNode,
  type TtsSentenceTiming,
  type TtsWordTiming,
} from '../../api/study'
import { useAppStore } from '../../store/useAppStore'
import { useStudyStore } from '../../store/useStudyStore'
import { getLanguageExtension } from './CodeChallengeInput'
import {
  splitStoryParagraphSentences,
  useSpeech,
  type StorySentence,
  type StoryWord,
} from './useSpeech'

interface Props {
  courseId: string
  node: PackNode
  worldMetaphor: string | null
  onEvaluate: () => void
  onRegenerateStory: () => Promise<void>
  onAskTutor: (ctx: { prompt: string; banner: string; autoSend?: boolean }) => void
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
      const endVal =
        nextStart !== undefined ? Math.max(t.end, nextStart) : Math.max(t.end, audioDuration || t.end)
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

function buildWordWindows(
  sentences: StorySentence[],
  flatWords: StoryWord[],
  sentenceWindows: { start: number; end: number }[],
  serverWords: TtsWordTiming[],
): { start: number; end: number; sentenceIndex: number }[] {
  if (flatWords.length === 0) return []

  if (serverWords.length === flatWords.length) {
    return flatWords.map((fw, idx) => {
      const sw = serverWords[idx]
      const nextStart = idx < serverWords.length - 1 ? serverWords[idx + 1].start : undefined
      const endVal = nextStart !== undefined ? Math.max(sw.end, nextStart) : sw.end
      return {
        start: sw.start,
        end: Math.max(sw.start + 0.04, endVal),
        sentenceIndex: fw.sentenceIndex,
      }
    })
  }

  if (serverWords.length > 0) {
    // Mapear cada palabra del DOM proporcionalmente sobre los eventos WordBoundary reales de edge-tts
    const totalServer = serverWords.length
    const totalDom = flatWords.length
    return flatWords.map((fw, idx) => {
      const mappedIdx = Math.min(
        totalServer - 1,
        Math.floor((idx / Math.max(1, totalDom)) * totalServer),
      )
      const nextMappedIdx = Math.min(
        totalServer - 1,
        Math.floor(((idx + 1) / Math.max(1, totalDom)) * totalServer),
      )
      const start = serverWords[mappedIdx].start
      const rawEnd =
        nextMappedIdx > mappedIdx
          ? serverWords[nextMappedIdx].start
          : serverWords[mappedIdx].end
      return {
        start,
        end: Math.max(start + 0.04, rawEnd),
        sentenceIndex: fw.sentenceIndex,
      }
    })
  }

  // Fallback proporcional por palabra dentro de cada ventana de oracion
  const out: { start: number; end: number; sentenceIndex: number }[] = []
  sentences.forEach((sent, sIdx) => {
    const sWin = sentenceWindows[sIdx] ?? { start: sIdx * 3, end: (sIdx + 1) * 3 }
    const sWords = sent.words
    if (sWords.length === 0) return
    const sDur = Math.max(0.15, sWin.end - sWin.start)
    const weights = sWords.map((w) => Math.max(1, w.text.length))
    const totalW = weights.reduce((a, b) => a + b, 0)
    let acc = 0
    sWords.forEach((w, wIdx) => {
      const wStart = sWin.start + (acc / totalW) * sDur
      acc += weights[wIdx]
      const wEnd = wIdx === sWords.length - 1 ? sWin.end : sWin.start + (acc / totalW) * sDur
      out.push({
        start: Math.round(wStart * 1000) / 1000,
        end: Math.round(Math.max(wStart + 0.04, wEnd) * 1000) / 1000,
        sentenceIndex: w.sentenceIndex,
      })
    })
  })
  return out
}

export default function StoryTab({
  courseId,
  node,
  worldMetaphor,
  onEvaluate,
  onRegenerateStory,
  onAskTutor,
}: Props) {
  const explanationStyle = useStudyStore((s) => s.explanationStyle)
  const setExplanationStyle = useStudyStore((s) => s.setExplanationStyle)
  const speech = useSpeech(node.story_script)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const blobUrlRef = useRef<string | null>(null)
  const ttsAbortRef = useRef<AbortController | null>(null)
  const ttsRequestTokenRef = useRef(0)
  const sentenceRefs = useRef<Record<number, HTMLSpanElement | null>>({})
  const wordRefs = useRef<Record<number, HTMLSpanElement | null>>({})
  const lastManualScrollRef = useRef<number>(0)

  const [mode, setMode] = useState<'neural' | 'fallback'>('neural')
  const [loadingAudio, setLoadingAudio] = useState(false)
  const [audioProgressPct, setAudioProgressPct] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState(1.0)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [serverTimings, setServerTimings] = useState<TtsSentenceTiming[]>([])
  const [serverWords, setServerWords] = useState<TtsWordTiming[]>([])
  const [regenerating, setRegenerating] = useState(false)
  const [quickQuestion, setQuickQuestion] = useState('')

  const {
    blocks: storyBlocks,
    flat: flatSentences,
    flatWords,
  } = useMemo(() => splitStoryParagraphSentences(node.story_script), [node.story_script])

  const sentenceWindows = useMemo(
    () => buildSentenceWindows(flatSentences, serverTimings, duration),
    [flatSentences, serverTimings, duration],
  )

  const wordWindows = useMemo(
    () => buildWordWindows(flatSentences, flatWords, sentenceWindows, serverWords),
    [flatSentences, flatWords, sentenceWindows, serverWords],
  )

  // Loop de alta frecuencia (requestAnimationFrame) mientras el audio neural esta reproduciendose
  useEffect(() => {
    if (!playing || mode !== 'neural') return
    let rafId = 0
    const tick = () => {
      if (audioRef.current && !audioRef.current.paused) {
        setCurrentTime(audioRef.current.currentTime)
        rafId = window.requestAnimationFrame(tick)
      }
    }
    rafId = window.requestAnimationFrame(tick)
    return () => {
      if (rafId) window.cancelAnimationFrame(rafId)
    }
  }, [playing, mode])

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

  const cancelPendingTts = () => {
    ttsRequestTokenRef.current += 1
    if (ttsAbortRef.current) {
      ttsAbortRef.current.abort()
      ttsAbortRef.current = null
    }
    setLoadingAudio(false)
    setAudioProgressPct(0)
  }

  // Avance compacto en % mientras edge-tts sintetiza el audio (sin ocupar barra extra)
  useEffect(() => {
    if (!loadingAudio) return
    const startedAt = Date.now()
    const expectedMs = Math.max(2400, Math.min(12000, flatWords.length * 24))
    setAudioProgressPct(6)
    const id = window.setInterval(() => {
      const elapsed = Date.now() - startedAt
      const pct = Math.min(94, Math.round(6 + 88 * (1 - Math.exp((-elapsed / expectedMs) * 2.1))))
      setAudioProgressPct(pct)
    }, 120)
    return () => window.clearInterval(id)
  }, [loadingAudio, flatWords.length])

  // Limpiar audio y cancelar descargas pendientes al cambiar de nodo o de story_script
  useEffect(() => {
    cancelPendingTts()
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
    setServerWords([])
    setMode('neural')
    return () => {
      cancelPendingTts()
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

  const loadNeuralAudio = async (opts?: { seekToWordIdx?: number; seekToSentenceIdx?: number }) => {
    cancelPendingTts()
    const token = ttsRequestTokenRef.current
    const controller = new AbortController()
    ttsAbortRef.current = controller
    setLoadingAudio(true)
    try {
      const blob = await fetchNodeTtsBlob(courseId, node.id, controller.signal)
      if (token !== ttsRequestTokenRef.current || controller.signal.aborted) return
      setAudioProgressPct(97)
      const fetchedData = await fetchNodeTtsTimingsData(courseId, node.id, controller.signal)
      if (token !== ttsRequestTokenRef.current || controller.signal.aborted) return
      setAudioProgressPct(100)
      setServerTimings(fetchedData.sentences)
      setServerWords(fetchedData.words)

      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current)
      }
      const url = URL.createObjectURL(blob)
      blobUrlRef.current = url
      const audio = new Audio(url)
      audio.playbackRate = rate
      audio.addEventListener('timeupdate', () => setCurrentTime(audio.currentTime))
      audio.addEventListener('loadedmetadata', () => {
        const dur = audio.duration || 0
        setDuration(dur)
        const sWins = buildSentenceWindows(flatSentences, fetchedData.sentences, dur)
        const wWins = buildWordWindows(flatSentences, flatWords, sWins, fetchedData.words)
        if (opts?.seekToWordIdx !== undefined) {
          const target = wWins[opts.seekToWordIdx]?.start ?? 0
          audio.currentTime = target
          setCurrentTime(target)
        } else if (opts?.seekToSentenceIdx !== undefined) {
          const target = sWins[opts.seekToSentenceIdx]?.start ?? 0
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
      if (token !== ttsRequestTokenRef.current || controller.signal.aborted) {
        URL.revokeObjectURL(url)
        blobUrlRef.current = null
        return
      }
      audioRef.current = audio
      await audio.play()
    } catch {
      // Si fue cancelado por cambio de nodo, "Detener" u "Otra explicación", descartar sin activar fallback
      if (token !== ttsRequestTokenRef.current || controller.signal.aborted) return
      // Fallback offline a speechSynthesis del navegador
      setMode('fallback')
      speech.setRate(rate)
      if (opts?.seekToSentenceIdx !== undefined) {
        speech.playFromSentence(opts.seekToSentenceIdx)
      } else {
        speech.play()
      }
    } finally {
      if (token === ttsRequestTokenRef.current) {
        ttsAbortRef.current = null
        setLoadingAudio(false)
        setAudioProgressPct(0)
      }
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

  const handleWordClick = async (globalWordIdx: number, sentenceIdx: number) => {
    if (mode === 'fallback') {
      speech.playFromSentence(sentenceIdx)
      return
    }

    if (audioRef.current) {
      const targetStart =
        wordWindows[globalWordIdx]?.start ?? sentenceWindows[sentenceIdx]?.start ?? 0
      audioRef.current.currentTime = targetStart
      setCurrentTime(targetStart)
      if (!playing) {
        await audioRef.current.play()
      }
      return
    }

    await loadNeuralAudio({ seekToWordIdx: globalWordIdx, seekToSentenceIdx: sentenceIdx })
  }

  const stopAudio = () => {
    cancelPendingTts()
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

  const activeWordIndex = useMemo(() => {
    if (mode === 'fallback') return null
    if (!playing && currentTime <= 0) return null
    if (wordWindows.length === 0) return null
    for (let i = 0; i < wordWindows.length; i++) {
      const w = wordWindows[i]
      if (currentTime >= w.start && currentTime < w.end) {
        return i
      }
    }
    if (currentTime >= wordWindows[wordWindows.length - 1].start) {
      return wordWindows.length - 1
    }
    return 0
  }, [currentTime, mode, playing, wordWindows])

  const activeSentenceIndex = useMemo(() => {
    if (mode === 'fallback') {
      return speech.activeSentenceIndex
    }
    if (activeWordIndex !== null && wordWindows[activeWordIndex]) {
      return wordWindows[activeWordIndex].sentenceIndex
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
  }, [activeWordIndex, currentTime, mode, playing, sentenceWindows, speech.activeSentenceIndex, wordWindows])

  // Auto-scroll suave a la palabra/oracion activa sin secuestrar el scroll manual
  useEffect(() => {
    if (!isPlaying) return
    if (Date.now() - lastManualScrollRef.current < 2500) return
    const targetEl =
      (activeWordIndex !== null ? wordRefs.current[activeWordIndex] : null) ??
      (activeSentenceIndex !== null ? sentenceRefs.current[activeSentenceIndex] : null)
    if (targetEl && typeof targetEl.scrollIntoView === 'function') {
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [activeWordIndex, activeSentenceIndex, isPlaying])

  const regenerateControls = (
    <div className="flex flex-wrap items-center gap-1.5">
      <select
        aria-label="Estilo de explicación"
        value={explanationStyle}
        onChange={(e) => setExplanationStyle(e.target.value as ExplanationStyle)}
        className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
      >
        <option value="narrative">Estilo: Narrativo</option>
        <option value="direct">Estilo: Directo</option>
        <option value="structured">Estilo: Estructurado</option>
      </select>
      <button
        type="button"
        disabled={regenerating}
        onClick={handleRegenerate}
        title="Genera otra explicación usando el estilo pedagógico seleccionado"
        className="inline-flex shrink-0 items-center gap-1.5 rounded border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:bg-slate-900 dark:hover:bg-slate-800"
      >
        <RefreshCw size={13} className={regenerating ? 'animate-spin' : ''} />
        {regenerating ? 'Re-explicando...' : 'Otra explicación'}
      </button>
    </div>
  )

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
          {regenerateControls}
        </div>
      )}

      {!worldMetaphor && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="min-w-0 flex-1 break-words text-sm text-slate-600 dark:text-slate-300">
            {node.summary}
          </p>
          {regenerateControls}
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
          <Loader2 size={14} className="shrink-0 animate-spin text-indigo-600 dark:text-indigo-400" />
          <span>
            Redactando otra explicación (~200 palabras) con el estilo seleccionado...
          </span>
        </div>
      )}

      <div className="flex flex-col gap-2 rounded-md border border-slate-200 p-2.5 dark:border-slate-700">
        <div className="flex flex-wrap items-center gap-2">
          <Volume2 size={16} className="text-slate-500" />
          <button
            type="button"
            disabled={loadingAudio || regenerating}
            onClick={togglePlay}
            className="inline-flex items-center gap-1 rounded border border-slate-300 px-2.5 py-1 text-xs font-medium tabular-nums hover:bg-slate-100 disabled:opacity-60 dark:border-slate-600 dark:hover:bg-slate-800"
          >
            {loadingAudio ? (
              <Loader2 size={14} className="animate-spin" />
            ) : isPlaying ? (
              <Pause size={14} />
            ) : (
              <Play size={14} />
            )}
            {loadingAudio
              ? `Generando ${audioProgressPct}%`
              : isPlaying
                ? 'Pausar'
                : 'Escuchar'}
          </button>
          <button
            type="button"
            onClick={stopAudio}
            disabled={!isPlaying && currentTime === 0 && !loadingAudio}
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
              step={0.1}
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
            ? 'Voz neural edge-tts en español · Haz clic en cualquier palabra para saltar a ese instante del audio.'
            : 'Fallback offline: síntesis de voz local del navegador · Haz clic en cualquier palabra u oración para escucharla.'}
        </span>
      </div>

      <article className="flex min-w-0 flex-col gap-3 break-words text-[15px] leading-relaxed">
        {storyBlocks.map((block, bIdx) => {
          if (block.type === 'code') {
            return (
              <StoryCodeBlock
                key={`code-${bIdx}`}
                courseId={courseId}
                language={block.language}
                code={block.code}
              />
            )
          }

          const pSentences = block.sentences
          return (
            <p key={`p-${block.paragraphIndex}-${bIdx}`} className="break-words">
              {pSentences.map((s, sIdx) => {
                const isActiveSentence = activeSentenceIndex === s.globalIndex
                return (
                  <span
                    key={s.globalIndex}
                    ref={(el) => {
                      sentenceRefs.current[s.globalIndex] = el
                    }}
                    className={`rounded-[2px] transition-colors ${
                      isActiveSentence ? 'bg-indigo-50/70 dark:bg-indigo-950/40' : ''
                    }`}
                  >
                    {s.words.map((w, wIdx) => {
                      const isActiveWord = activeWordIndex === w.globalWordIndex
                      return (
                        <span key={w.globalWordIndex}>
                          <span
                            ref={(el) => {
                              wordRefs.current[w.globalWordIndex] = el
                            }}
                            role="button"
                            tabIndex={0}
                            title="Clic para saltar a esta palabra en el audio"
                            onClick={() => void handleWordClick(w.globalWordIndex, s.globalIndex)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault()
                                void handleWordClick(w.globalWordIndex, s.globalIndex)
                              }
                            }}
                            className={`cursor-pointer rounded-[2px] transition-colors ${
                              w.inlineCode
                                ? 'font-mono text-[0.9em] bg-slate-100 dark:bg-slate-800 px-1 rounded'
                                : ''
                            } ${
                              w.highlighted
                                ? 'font-semibold text-slate-950 dark:text-white bg-amber-100/75 dark:bg-amber-900/35 px-0.5 rounded-[2px]'
                                : ''
                            } ${
                              isActiveWord
                                ? 'bg-indigo-100 dark:bg-indigo-900/60 border-b-2 border-indigo-500 dark:border-indigo-400 rounded-[2px]'
                                : 'hover:bg-slate-200/60 dark:hover:bg-slate-800/70'
                            }`}
                          >
                            {w.text}
                          </span>
                          {wIdx < s.words.length - 1 ? ' ' : ''}
                        </span>
                      )
                    })}
                    {sIdx < pSentences.length - 1 ? ' ' : ''}
                  </span>
                )
              })}
            </p>
          )
        })}
      </article>

      <div className="flex flex-col gap-3 pt-1">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onEvaluate}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
          >
            <Swords size={16} /> Evaluarme a ciegas
          </button>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            const q = quickQuestion.trim()
            if (!q) return
            setQuickQuestion('')
            onAskTutor({
              prompt: q,
              banner: `Consultando sobre la historia del nodo "${node.title}" (${node.block}).`,
              autoSend: true,
            })
          }}
          className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50/70 p-2 dark:border-slate-700 dark:bg-slate-800/50"
        >
          <MessageSquare size={15} className="ml-1 shrink-0 text-slate-500 dark:text-slate-400" />
          <input
            type="text"
            value={quickQuestion}
            onChange={(e) => setQuickQuestion(e.target.value)}
            placeholder="¿Alguna duda sobre este tema? Pregúntale al tutor..."
            className="min-w-0 flex-1 rounded border border-slate-300 bg-white px-2.5 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:border-slate-600 dark:bg-slate-900"
          />
          <button
            type="submit"
            disabled={!quickQuestion.trim()}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-40 dark:bg-indigo-500 dark:hover:bg-indigo-400"
          >
            <Send size={13} />
            Enviar
          </button>
        </form>
      </div>
    </div>
  )
}

function StoryCodeBlock({
  courseId,
  language,
  code,
}: {
  courseId: string
  language: string
  code: string
}) {
  const theme = useAppStore((s) => s.theme)
  const [copied, setCopied] = useState(false)
  const [loadingVoice, setLoadingVoice] = useState(false)
  const [playingVoice, setPlayingVoice] = useState(false)
  const voiceAudioRef = useRef<HTMLAudioElement | null>(null)
  const voiceUrlRef = useRef<string | null>(null)
  const voiceAbortRef = useRef<AbortController | null>(null)

  const normLang = (language || '').trim().toLowerCase()
  const isEnglishExamples = normLang === 'en' || normLang === 'english' || normLang === 'en-us'
  const extensions = useMemo(() => getLanguageExtension(language), [language])
  const cmTheme = theme === 'dark' ? oneDark : 'light'
  const langLabel = (language || 'java').toUpperCase()

  const stopVoice = () => {
    voiceAbortRef.current?.abort()
    voiceAbortRef.current = null
    if (voiceAudioRef.current) {
      voiceAudioRef.current.pause()
      voiceAudioRef.current = null
    }
    if (voiceUrlRef.current) {
      URL.revokeObjectURL(voiceUrlRef.current)
      voiceUrlRef.current = null
    }
    setLoadingVoice(false)
    setPlayingVoice(false)
  }

  useEffect(() => () => stopVoice(), [code])

  const handlePlayEnglish = async () => {
    if (loadingVoice || playingVoice) {
      stopVoice()
      return
    }
    // Quitar traducciones entre parentesis y viñetas para pronunciar solo las frases en ingles
    const englishOnly = code
      .split('\n')
      .map((line) =>
        line
          .replace(/^[-*•]\s*/, '')
          .replace(/^(?:Affirmative|Negative|Question|Example\s*\d*|Afirmativa|Negativa|Pregunta)\s*:\s*/i, '')
          .replace(/\([^)]*\)/g, '')
          .trim(),
      )
      .filter(Boolean)
      .join('. ')
      .slice(0, 1150)

    if (!englishOnly) return
    setLoadingVoice(true)
    const ctrl = new AbortController()
    voiceAbortRef.current = ctrl
    try {
      const blob = await fetchPhraseTtsBlob(courseId, englishOnly, 'en', 'us', ctrl.signal)
      if (ctrl.signal.aborted) return
      const url = URL.createObjectURL(blob)
      voiceUrlRef.current = url
      const audio = new Audio(url)
      voiceAudioRef.current = audio
      audio.onended = () => setPlayingVoice(false)
      audio.onerror = () => setPlayingVoice(false)
      setLoadingVoice(false)
      setPlayingVoice(true)
      await audio.play()
    } catch {
      if (!ctrl.signal.aborted) {
        setLoadingVoice(false)
        setPlayingVoice(false)
      }
    }
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setCopied(false)
    }
  }

  if (isEnglishExamples) {
    const lines = code
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
    return (
      <div className="my-1 overflow-hidden rounded-md border border-sky-300/80 bg-sky-50/40 text-sm dark:border-sky-800/70 dark:bg-sky-950/25">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-sky-200/80 bg-sky-100/60 px-3 py-1.5 dark:border-sky-800/60 dark:bg-sky-950/50">
          <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-sky-900 dark:text-sky-200">
            <Languages size={13} className="text-sky-600 dark:text-sky-400" />
            Ejemplos en inglés
          </span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => void handlePlayEnglish()}
              className="inline-flex items-center gap-1 rounded border border-sky-300 bg-white px-2 py-0.5 text-[11px] font-medium text-sky-900 hover:bg-sky-50 dark:border-sky-700 dark:bg-slate-900 dark:text-sky-200 dark:hover:bg-sky-950"
            >
              {loadingVoice ? (
                <Loader2 size={12} className="animate-spin" />
              ) : playingVoice ? (
                <Square size={11} />
              ) : (
                <Volume2 size={12} />
              )}
              {loadingVoice ? 'Cargando...' : playingVoice ? 'Detener' : 'Escuchar en inglés'}
            </button>
            <button
              type="button"
              onClick={() => void handleCopy()}
              className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              {copied ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
              {copied ? 'Copiado' : 'Copiar'}
            </button>
          </div>
        </div>
        <ul className="flex flex-col gap-1.5 p-3 text-sm leading-relaxed text-slate-900 dark:text-slate-100">
          {lines.map((ln, idx) => (
            <li key={idx} className="break-words">
              {ln.replace(/^[-*•]\s*/, '')}
            </li>
          ))}
        </ul>
      </div>
    )
  }

  return (
    <div className="my-1 overflow-hidden rounded-md border border-slate-300 bg-slate-50 text-xs dark:border-slate-700 dark:bg-slate-900/80">
      <div className="flex items-center justify-between border-b border-slate-200 bg-slate-100/80 px-3 py-1.5 dark:border-slate-700 dark:bg-slate-800/80">
        <span className="inline-flex items-center gap-1.5 font-mono text-[11px] font-semibold uppercase text-slate-700 dark:text-slate-300">
          <Code2 size={13} className="text-indigo-600 dark:text-indigo-400" />
          Ejemplo · {langLabel}
        </span>
        <button
          type="button"
          onClick={() => void handleCopy()}
          className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          {copied ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
          {copied ? 'Copiado' : 'Copiar'}
        </button>
      </div>
      <CodeMirror
        value={code}
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
  )
}
