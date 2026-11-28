import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Cpu,
  Film,
  Layers,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Shield,
  Sparkles,
  VolumeX,
  X,
  Zap,
} from 'lucide-react'
import {
  getNodeCinemaReel,
  streamNodeCinemaReel,
  type CinemaAct,
  type CinemaActKind,
  type CinemaReelStreamProgress,
  type CinemaVisualNode,
  type NodeCinemaReelResponse,
} from '../../api/study'

export interface CinemaReelModalProps {
  courseId: string
  nodeId: string
  nodeTitle: string
  open: boolean
  onClose: () => void
}

const ACT_KIND_LABEL: Record<CinemaActKind, string> = {
  hook: 'Gancho',
  analogy: 'Analogía',
  mechanism: 'Mecanismo',
  payoff: 'Impacto',
  takeaway: 'Claves',
}

const PLAYBACK_RATES = [1, 1.25, 1.5] as const
type PlaybackRate = (typeof PLAYBACK_RATES)[number]

function formatTime(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '0:00'
  const total = Math.floor(sec)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s < 10 ? '0' : ''}${s}`
}

function clamp(val: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, val))
}

function buildAudioUrl(rawUrl: string, updatedAt?: string): string {
  if (!updatedAt) return rawUrl
  const sep = rawUrl.includes('?') ? '&' : '?'
  return `${rawUrl}${sep}v=${encodeURIComponent(updatedAt)}`
}

function defaultStageLabel(stage?: CinemaReelStreamProgress['stage']): string {
  switch (stage) {
    case 'analyzing':
      return 'Analizando concepto...'
    case 'scripting':
      return 'Escribiendo guion...'
    case 'synthesizing_audio':
      return 'Sintetizando narración neural...'
    case 'done':
      return 'Mini-video listo'
    default:
      return 'Analizando concepto...'
  }
}

function stageCeiling(stage?: CinemaReelStreamProgress['stage']): number {
  switch (stage) {
    case 'analyzing':
      return 48
    case 'scripting':
      return 82
    case 'synthesizing_audio':
      return 96
    case 'done':
      return 100
    default:
      return 42
  }
}

interface ToneClasses {
  card: string
  accent: string
  badge: string
  ring: string
  stroke: string
}

function getToneClasses(tone: string, status?: string): ToneClasses {
  const normTone = (tone || '').toLowerCase()
  const normStatus = (status || '').toLowerCase()
  const resolved =
    normTone ||
    (normStatus === 'problem'
      ? 'rose'
      : normStatus === 'solved' || normStatus === 'new'
        ? 'emerald'
        : normStatus === 'core'
          ? 'indigo'
          : 'slate')

  switch (resolved) {
    case 'emerald':
      return {
        card: 'border-emerald-300/90 bg-emerald-50/80 text-emerald-950 dark:border-emerald-700/80 dark:bg-emerald-950/40 dark:text-emerald-100',
        accent: 'text-emerald-600 dark:text-emerald-400',
        badge: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/70 dark:text-emerald-200',
        ring: 'ring-2 ring-emerald-500/40 dark:ring-emerald-400/40',
        stroke: '#10b981',
      }
    case 'amber':
      return {
        card: 'border-amber-300/90 bg-amber-50/80 text-amber-950 dark:border-amber-700/80 dark:bg-amber-950/35 dark:text-amber-100',
        accent: 'text-amber-600 dark:text-amber-400',
        badge: 'bg-amber-100 text-amber-900 dark:bg-amber-900/70 dark:text-amber-200',
        ring: 'ring-2 ring-amber-500/40 dark:ring-amber-400/40',
        stroke: '#f59e0b',
      }
    case 'rose':
      return {
        card: 'border-rose-300/90 bg-rose-50/80 text-rose-950 dark:border-rose-700/80 dark:bg-rose-950/35 dark:text-rose-100',
        accent: 'text-rose-600 dark:text-rose-400',
        badge: 'bg-rose-100 text-rose-900 dark:bg-rose-900/70 dark:text-rose-200',
        ring: 'ring-2 ring-rose-500/40 dark:ring-rose-400/40',
        stroke: '#f43f5e',
      }
    case 'sky':
      return {
        card: 'border-sky-300/90 bg-sky-50/80 text-sky-950 dark:border-sky-700/80 dark:bg-sky-950/35 dark:text-sky-100',
        accent: 'text-sky-600 dark:text-sky-400',
        badge: 'bg-sky-100 text-sky-900 dark:bg-sky-900/70 dark:text-sky-200',
        ring: 'ring-2 ring-sky-500/40 dark:ring-sky-400/40',
        stroke: '#0ea5e9',
      }
    case 'indigo':
      return {
        card: 'border-indigo-300/90 bg-indigo-50/80 text-indigo-950 dark:border-indigo-700/80 dark:bg-indigo-950/40 dark:text-indigo-100',
        accent: 'text-indigo-600 dark:text-indigo-400',
        badge: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/70 dark:text-indigo-200',
        ring: 'ring-2 ring-indigo-500/45 dark:ring-indigo-400/45',
        stroke: '#6366f1',
      }
    default:
      return {
        card: 'border-slate-300 bg-white text-slate-900 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-100',
        accent: 'text-slate-600 dark:text-slate-300',
        badge: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
        ring: 'ring-2 ring-slate-400/40 dark:ring-slate-500/40',
        stroke: '#64748b',
      }
  }
}

function StatusIcon({ status, className }: { status: string; className?: string }) {
  switch ((status || '').toLowerCase()) {
    case 'problem':
      return <AlertTriangle size={15} className={className} />
    case 'solved':
      return <CheckCircle2 size={15} className={className} />
    case 'new':
      return <Sparkles size={15} className={className} />
    case 'core':
      return <Shield size={15} className={className} />
    case 'active':
      return <Zap size={15} className={className} />
    default:
      return <Layers size={15} className={className} />
  }
}

function statusBadgeText(status: string): string | null {
  switch ((status || '').toLowerCase()) {
    case 'problem':
      return 'Fricción'
    case 'solved':
      return 'Resuelto'
    case 'new':
      return 'Nuevo'
    case 'core':
      return 'Núcleo intacto'
    case 'active':
      return 'Activo'
    default:
      return null
  }
}

interface WordSpan {
  word: string
  startRatio: number
  endRatio: number
}

function buildKineticWords(text: string): WordSpan[] {
  const words = text
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 0)
  if (words.length === 0) return []

  const weights = words.map((w) => {
    const cleanLen = w.replace(/[^\p{L}\p{N}]/gu, '').length
    const base = Math.max(2, cleanLen)
    const pauseBonus = /[.!?]$/.test(w) ? 4 : /[,;:]$/.test(w) ? 2 : 0
    return base + pauseBonus
  })
  const totalWeight = weights.reduce((acc, n) => acc + n, 0)
  let acc = 0

  return words.map((word, idx) => {
    const startRatio = acc / totalWeight
    acc += weights[idx]
    const endRatio = idx === words.length - 1 ? 1 : acc / totalWeight
    return { word, startRatio, endRatio }
  })
}

export default function CinemaReelModal({
  courseId,
  nodeId,
  nodeTitle,
  open,
  onClose,
}: CinemaReelModalProps) {
  const [reel, setReel] = useState<NodeCinemaReelResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState<CinemaReelStreamProgress | null>(null)
  const [displayPct, setDisplayPct] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const [actIdx, setActIdx] = useState(0)
  const [actTime, setActTime] = useState(0)
  const [durations, setDurations] = useState<number[]>([])
  const [isPlaying, setIsPlaying] = useState(false)
  const [hasEnded, setHasEnded] = useState(false)
  const [playbackRate, setPlaybackRate] = useState<PlaybackRate>(1)
  const [visualOnlyMode, setVisualOnlyMode] = useState(false)
  const [reloadNonce, setReloadNonce] = useState(0)

  const fetchAbortRef = useRef<AbortController | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const rafRef = useRef<number>(0)
  const lastFrameTsRef = useRef<number>(0)
  const pendingSeekRef = useRef<number | null>(null)
  const shouldPlayOnLoadRef = useRef<boolean>(false)
  const playbackRateRef = useRef<PlaybackRate>(1)
  const actIdxRef = useRef<number>(0)
  const actTimeRef = useRef<number>(0)
  const durationsRef = useRef<number[]>([])
  const actsRef = useRef<CinemaAct[]>([])
  const timelineRef = useRef<HTMLDivElement | null>(null)

  const acts = useMemo(() => reel?.acts ?? [], [reel])
  const safeActIdx = acts.length > 0 ? clamp(actIdx, 0, acts.length - 1) : 0
  const currentAct: CinemaAct | undefined = acts[safeActIdx]

  useEffect(() => {
    playbackRateRef.current = playbackRate
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackRate
    }
  }, [playbackRate])

  useEffect(() => {
    actIdxRef.current = safeActIdx
  }, [safeActIdx])

  useEffect(() => {
    actTimeRef.current = actTime
  }, [actTime])

  useEffect(() => {
    durationsRef.current = durations
  }, [durations])

  useEffect(() => {
    actsRef.current = acts
  }, [acts])

  const stopAndReleaseAudio = useCallback(() => {
    if (rafRef.current) {
      window.cancelAnimationFrame(rafRef.current)
      rafRef.current = 0
    }
    if (audioRef.current) {
      audioRef.current.onended = null
      audioRef.current.onerror = null
      audioRef.current.onloadedmetadata = null
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
    }
  }, [])

  const startReelGeneration = useCallback(
    async (force: boolean) => {
      fetchAbortRef.current?.abort()
      stopAndReleaseAudio()

      const ctrl = new AbortController()
      fetchAbortRef.current = ctrl
      setLoading(true)
      setError(null)
      setIsPlaying(false)
      setHasEnded(false)
      setVisualOnlyMode(false)
      setActIdx(0)
      setActTime(0)
      pendingSeekRef.current = null
      shouldPlayOnLoadRef.current = true
      setProgress({
        stage: 'analyzing',
        pct: 12,
        label: 'Analizando concepto...',
      })
      setDisplayPct(12)

      try {
        let fetched: NodeCinemaReelResponse | null = null
        if (!force) {
          fetched = await getNodeCinemaReel(courseId, nodeId, ctrl.signal)
        }
        if (ctrl.signal.aborted) return

        if (!fetched || !Array.isArray(fetched.acts) || fetched.acts.length === 0) {
          fetched = await streamNodeCinemaReel(courseId, nodeId, {
            force,
            signal: ctrl.signal,
            onProgress: (p) => {
              if (!ctrl.signal.aborted) setProgress(p)
            },
          })
        }
        if (ctrl.signal.aborted) return

        const initialDurations = fetched.acts.map((a) => Math.max(3, Number(a.estimated_sec) || 10))
        setReel(fetched)
        setDurations(initialDurations)
        setActIdx(0)
        setActTime(0)
        setHasEnded(false)
        setDisplayPct(100)
        setReloadNonce((n) => n + 1)
      } catch (err) {
        if (ctrl.signal.aborted) return
        setError(
          err instanceof Error
            ? err.message
            : 'No se pudo preparar el mini-video en Modo Cine.',
        )
      } finally {
        if (fetchAbortRef.current === ctrl) {
          fetchAbortRef.current = null
          setLoading(false)
        }
      }
    },
    [courseId, nodeId, stopAndReleaseAudio],
  )

  // Cargar al abrir o cambiar de nodo
  useEffect(() => {
    if (!open) {
      fetchAbortRef.current?.abort()
      fetchAbortRef.current = null
      stopAndReleaseAudio()
      setIsPlaying(false)
      return
    }
    void startReelGeneration(false)

    return () => {
      fetchAbortRef.current?.abort()
      fetchAbortRef.current = null
      stopAndReleaseAudio()
    }
  }, [open, courseId, nodeId, startReelGeneration, stopAndReleaseAudio])

  // Interpolacion suave del % de carga
  useEffect(() => {
    if (!loading) return
    setDisplayPct((prev) => {
      const incoming = Math.round(progress?.pct ?? 12)
      return prev >= 100 ? Math.max(12, incoming) : Math.max(prev, incoming)
    })
  }, [loading, progress?.pct])

  useEffect(() => {
    if (!loading) return
    const ceiling = stageCeiling(progress?.stage)
    const id = window.setInterval(() => {
      setDisplayPct((prev) => {
        const floor = Math.round(progress?.pct ?? 12)
        const base = Math.max(prev, floor)
        if (base < ceiling) return base + 1
        return base
      })
    }, 380)
    return () => window.clearInterval(id)
  }, [loading, progress?.stage, progress?.pct])

  const advanceToNextActOrFinish = useCallback(() => {
    const currentIndex = actIdxRef.current
    const totalActs = actsRef.current.length
    if (currentIndex < totalActs - 1) {
      pendingSeekRef.current = 0
      shouldPlayOnLoadRef.current = true
      setActTime(0)
      setActIdx(currentIndex + 1)
    } else {
      const lastDur =
        durationsRef.current[currentIndex] ??
        Math.max(3, actsRef.current[currentIndex]?.estimated_sec ?? 10)
      setActTime(lastDur)
      setIsPlaying(false)
      setHasEnded(true)
      shouldPlayOnLoadRef.current = false
    }
  }, [])

  // Cargar el audio del acto actual (o activar modo visual si no hay audio_url)
  useEffect(() => {
    if (!open || loading || !reel || !currentAct) return
    stopAndReleaseAudio()

    const targetSeek = pendingSeekRef.current
    pendingSeekRef.current = null
    const wantPlay = shouldPlayOnLoadRef.current

    if (!currentAct.audio_url) {
      setVisualOnlyMode(true)
      const fallbackDur = Math.max(3, currentAct.estimated_sec || 10)
      const clampedStart = targetSeek !== null ? clamp(targetSeek, 0, fallbackDur) : 0
      setActTime(clampedStart)
      if (wantPlay) {
        setHasEnded(false)
        setIsPlaying(true)
      }
      return
    }

    let cancelled = false
    setVisualOnlyMode(false)
    const src = buildAudioUrl(currentAct.audio_url, reel.updated_at)
    const audio = new Audio(src)
    audio.preload = 'auto'
    audio.playbackRate = playbackRateRef.current
    audioRef.current = audio

    const applyPendingSeek = () => {
      if (cancelled) return
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        const realDur = audio.duration
        setDurations((prev) => {
          const next = [...prev]
          next[safeActIdx] = realDur
          return next
        })
        if (targetSeek !== null) {
          const clamped = clamp(targetSeek, 0, Math.max(0, realDur - 0.05))
          audio.currentTime = clamped
          setActTime(clamped)
        }
      } else if (targetSeek !== null) {
        audio.currentTime = Math.max(0, targetSeek)
        setActTime(Math.max(0, targetSeek))
      }
    }

    audio.onloadedmetadata = applyPendingSeek
    audio.onended = () => {
      if (cancelled) return
      advanceToNextActOrFinish()
    }
    audio.onerror = () => {
      if (cancelled) return
      audioRef.current = null
      setVisualOnlyMode(true)
      if (wantPlay) {
        setHasEnded(false)
        setIsPlaying(true)
      }
    }

    if (audio.readyState >= 1) {
      applyPendingSeek()
    } else if (targetSeek !== null) {
      setActTime(Math.max(0, targetSeek))
    } else {
      setActTime(0)
    }

    if (wantPlay) {
      setHasEnded(false)
      audio
        .play()
        .then(() => {
          if (cancelled) return
          setIsPlaying(true)
        })
        .catch((err: unknown) => {
          if (cancelled) return
          const isAutoplayBlocked =
            err instanceof DOMException && err.name === 'NotAllowedError'
          if (isAutoplayBlocked) {
            setIsPlaying(false)
            shouldPlayOnLoadRef.current = false
          } else {
            audioRef.current = null
            setVisualOnlyMode(true)
            setIsPlaying(true)
          }
        })
    }

    return () => {
      cancelled = true
      stopAndReleaseAudio()
    }
  }, [
    open,
    loading,
    reel,
    currentAct,
    safeActIdx,
    reloadNonce,
    stopAndReleaseAudio,
    advanceToNextActOrFinish,
  ])

  // Loop rAF para sincronizar progreso de subtítulos y timeline (audio real o temporizador visual)
  useEffect(() => {
    if (!open || !isPlaying || loading || !currentAct) {
      if (rafRef.current) {
        window.cancelAnimationFrame(rafRef.current)
        rafRef.current = 0
      }
      return
    }

    lastFrameTsRef.current = performance.now()

    const tick = (now: number) => {
      const dtSec = Math.max(0, (now - lastFrameTsRef.current) / 1000)
      lastFrameTsRef.current = now

      const audio = audioRef.current
      if (audio && !visualOnlyMode) {
        setActTime(audio.currentTime)
        rafRef.current = window.requestAnimationFrame(tick)
        return
      }

      const dur =
        durationsRef.current[actIdxRef.current] ??
        Math.max(3, actsRef.current[actIdxRef.current]?.estimated_sec ?? 10)
      const nextTime = actTimeRef.current + dtSec * playbackRateRef.current
      if (nextTime >= dur) {
        advanceToNextActOrFinish()
        return
      }
      actTimeRef.current = nextTime
      setActTime(nextTime)
      rafRef.current = window.requestAnimationFrame(tick)
    }

    rafRef.current = window.requestAnimationFrame(tick)
    return () => {
      if (rafRef.current) {
        window.cancelAnimationFrame(rafRef.current)
        rafRef.current = 0
      }
    }
  }, [open, isPlaying, loading, currentAct, visualOnlyMode, advanceToNextActOrFinish])

  const handleTogglePlay = useCallback(() => {
    if (loading || acts.length === 0) return

    if (hasEnded) {
      pendingSeekRef.current = 0
      shouldPlayOnLoadRef.current = true
      setHasEnded(false)
      setActTime(0)
      if (safeActIdx === 0) {
        const audio = audioRef.current
        if (audio && !visualOnlyMode) {
          audio.currentTime = 0
          audio
            .play()
            .then(() => setIsPlaying(true))
            .catch(() => {
              audioRef.current = null
              setVisualOnlyMode(true)
              setIsPlaying(true)
            })
        } else {
          setIsPlaying(true)
        }
      } else {
        setActIdx(0)
      }
      return
    }

    if (isPlaying) {
      shouldPlayOnLoadRef.current = false
      audioRef.current?.pause()
      setIsPlaying(false)
      return
    }

    shouldPlayOnLoadRef.current = true
    const audio = audioRef.current
    if (audio && !visualOnlyMode) {
      audio.playbackRate = playbackRateRef.current
      audio
        .play()
        .then(() => setIsPlaying(true))
        .catch(() => {
          audioRef.current = null
          setVisualOnlyMode(true)
          setIsPlaying(true)
        })
    } else {
      setIsPlaying(true)
    }
  }, [loading, acts.length, hasEnded, safeActIdx, isPlaying, visualOnlyMode])

  const handleRestart = useCallback(() => {
    if (acts.length === 0) return
    pendingSeekRef.current = 0
    shouldPlayOnLoadRef.current = true
    setHasEnded(false)
    setActTime(0)
    if (safeActIdx === 0) {
      const audio = audioRef.current
      if (audio && !visualOnlyMode) {
        audio.currentTime = 0
        audio
          .play()
          .then(() => setIsPlaying(true))
          .catch(() => {
            audioRef.current = null
            setVisualOnlyMode(true)
            setIsPlaying(true)
          })
      } else {
        setIsPlaying(true)
      }
    } else {
      setActIdx(0)
    }
  }, [acts.length, safeActIdx, visualOnlyMode])

  const jumpToAct = useCallback(
    (targetIdx: number, offsetSec = 0) => {
      if (acts.length === 0) return
      const clampedIdx = clamp(targetIdx, 0, acts.length - 1)
      const targetDur =
        durations[clampedIdx] ?? Math.max(3, acts[clampedIdx]?.estimated_sec ?? 10)
      const clampedOffset = clamp(offsetSec, 0, Math.max(0, targetDur - 0.05))
      setHasEnded(false)

      if (clampedIdx === safeActIdx) {
        const audio = audioRef.current
        if (audio && !visualOnlyMode) {
          audio.currentTime = clampedOffset
        }
        actTimeRef.current = clampedOffset
        setActTime(clampedOffset)
        return
      }

      pendingSeekRef.current = clampedOffset
      shouldPlayOnLoadRef.current = isPlaying || hasEnded
      actTimeRef.current = clampedOffset
      setActTime(clampedOffset)
      setActIdx(clampedIdx)
    },
    [acts, durations, safeActIdx, visualOnlyMode, isPlaying, hasEnded],
  )

  // Atajos de teclado: Escape para cerrar, Space para Play/Pausa
  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key === ' ' || e.code === 'Space') {
        const target = e.target as HTMLElement | null
        const tag = target?.tagName ?? ''
        if (
          tag === 'BUTTON' ||
          tag === 'INPUT' ||
          tag === 'SELECT' ||
          tag === 'TEXTAREA' ||
          tag === 'A'
        ) {
          return
        }
        e.preventDefault()
        handleTogglePlay()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose, handleTogglePlay])

  const actOffsets = useMemo(() => {
    const offsets: number[] = []
    let acc = 0
    for (let i = 0; i < acts.length; i++) {
      offsets.push(acc)
      acc += durations[i] ?? Math.max(3, acts[i].estimated_sec || 10)
    }
    return offsets
  }, [acts, durations])

  const totalDuration = useMemo(() => {
    if (acts.length === 0) return 0
    const lastIdx = acts.length - 1
    return (
      (actOffsets[lastIdx] ?? 0) +
      (durations[lastIdx] ?? Math.max(3, acts[lastIdx].estimated_sec || 10))
    )
  }, [acts, actOffsets, durations])

  const currentActDuration =
    durations[safeActIdx] ?? Math.max(3, currentAct?.estimated_sec ?? 10)
  const actProgress =
    currentActDuration > 0 ? clamp(actTime / currentActDuration, 0, 1) : 0
  const globalTime = (actOffsets[safeActIdx] ?? 0) + actTime
  const globalProgress = totalDuration > 0 ? clamp(globalTime / totalDuration, 0, 1) : 0

  const handleTimelineClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!timelineRef.current || totalDuration <= 0 || acts.length === 0) return
    const rect = timelineRef.current.getBoundingClientRect()
    const ratio = clamp((e.clientX - rect.left) / Math.max(1, rect.width), 0, 1)
    const targetGlobalSec = ratio * totalDuration

    let targetActIdx = acts.length - 1
    for (let i = 0; i < acts.length; i++) {
      const start = actOffsets[i] ?? 0
      const dur = durations[i] ?? Math.max(3, acts[i].estimated_sec || 10)
      if (targetGlobalSec <= start + dur || i === acts.length - 1) {
        targetActIdx = i
        break
      }
    }
    const offsetInAct = targetGlobalSec - (actOffsets[targetActIdx] ?? 0)
    jumpToAct(targetActIdx, offsetInAct)
  }

  const kineticWords = useMemo(
    () => buildKineticWords(currentAct?.narration_es ?? ''),
    [currentAct?.narration_es],
  )

  const activeWordIdx = useMemo(() => {
    if (kineticWords.length === 0) return -1
    if (!isPlaying && actTime <= 0.02 && !hasEnded) return -1
    if (hasEnded) return kineticWords.length
    for (let i = 0; i < kineticWords.length; i++) {
      if (actProgress <= kineticWords[i].endRatio) {
        return i
      }
    }
    return kineticWords.length - 1
  }, [kineticWords, isPlaying, actTime, hasEnded, actProgress])

  if (!open) return null

  const actKindLabel = currentAct
    ? (ACT_KIND_LABEL[currentAct.kind] ?? currentAct.title)
    : ''

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Modo Cine: ${nodeTitle}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-3 backdrop-blur-sm sm:p-6"
    >
      <style>{`
        @keyframes cinemaActEnter {
          0% { opacity: 0; transform: translateY(10px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        @keyframes cinemaCardPop {
          0% { opacity: 0; transform: translateY(8px) scale(0.97); }
          100% { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes cinemaDashFlow {
          0% { stroke-dashoffset: 24; }
          100% { stroke-dashoffset: 0; }
        }
        @keyframes cinemaPlugIn {
          0% { opacity: 0; transform: translateX(22px) scale(0.95); }
          100% { opacity: 1; transform: translateX(0) scale(1); }
        }
        @keyframes cinemaPulseDot {
          0%, 100% { transform: scale(1); opacity: 0.9; }
          50% { transform: scale(1.25); opacity: 1; }
        }
        .cinema-act-enter {
          animation: cinemaActEnter 420ms cubic-bezier(0.22, 1, 0.36, 1) both;
        }
        .cinema-card-pop {
          animation: cinemaCardPop 420ms cubic-bezier(0.22, 1, 0.36, 1) both;
        }
        .cinema-dash-flow {
          stroke-dasharray: 6 6;
          animation: cinemaDashFlow 900ms linear infinite;
        }
        .cinema-plug-in {
          animation: cinemaPlugIn 520ms cubic-bezier(0.22, 1, 0.36, 1) both;
        }
        .cinema-pulse-dot {
          animation: cinemaPulseDot 1.3s ease-in-out infinite;
        }
      `}</style>

      <div className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white text-slate-900 shadow-2xl dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100">
        {/* Barra superior minimalista */}
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/90 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-indigo-600 px-2.5 py-0.5 text-[11px] font-semibold tracking-wide text-white dark:bg-indigo-500">
              <Film size={12} />
              Modo Cine
            </span>
            <h2 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
              {reel?.title || nodeTitle}
            </h2>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {visualOnlyMode && !loading && !error && (
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2.5 py-0.5 text-[11px] font-medium text-amber-800 dark:border-amber-700/80 dark:bg-amber-950/50 dark:text-amber-200">
                <VolumeX size={12} />
                Sin audio (modo visual)
              </span>
            )}
            <button
              type="button"
              onClick={onClose}
              aria-label="Cerrar Modo Cine"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
            >
              <X size={16} />
            </button>
          </div>
        </header>

        {/* Cuerpo principal: Carga, Error o Escenario Cinético */}
        {loading ? (
          <div className="flex min-h-[24rem] flex-col items-center justify-center gap-5 px-6 py-10">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-indigo-200 bg-indigo-50 text-indigo-600 dark:border-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-400">
              <Loader2 size={24} className="animate-spin" />
            </div>

            <div className="w-full max-w-md text-center">
              <div className="flex items-center justify-between gap-2 text-xs font-medium text-slate-700 dark:text-slate-200">
                <span className="truncate">
                  {progress?.label?.trim() || defaultStageLabel(progress?.stage)}
                </span>
                <span className="font-mono font-semibold tabular-nums text-indigo-600 dark:text-indigo-400">
                  {clamp(displayPct, 0, 100)}%
                </span>
              </div>

              <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                <div
                  className="h-full rounded-full bg-indigo-600 transition-all duration-300 ease-out dark:bg-indigo-400"
                  style={{ width: `${clamp(displayPct, 4, 100)}%` }}
                />
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-center gap-1.5 text-[11px]">
                {(
                  [
                    { id: 'analyzing', text: '1. Analizando concepto' },
                    { id: 'scripting', text: '2. Escribiendo guion' },
                    { id: 'synthesizing_audio', text: '3. Narración neural' },
                  ] as const
                ).map((st, idx) => {
                  const order: CinemaReelStreamProgress['stage'][] = [
                    'analyzing',
                    'scripting',
                    'synthesizing_audio',
                  ]
                  const activeIdx = Math.max(0, order.indexOf(progress?.stage ?? 'analyzing'))
                  const done = idx < activeIdx
                  const current = idx === activeIdx
                  return (
                    <span
                      key={st.id}
                      className={`rounded-full px-2.5 py-0.5 font-medium ${
                        current
                          ? 'bg-indigo-600 text-white dark:bg-indigo-500'
                          : done
                            ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-300'
                            : 'bg-slate-100 text-slate-500 dark:bg-slate-900 dark:text-slate-400'
                      }`}
                    >
                      {st.text}
                    </span>
                  )
                })}
              </div>
            </div>

            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-300 bg-white px-4 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              Cancelar
            </button>
          </div>
        ) : error ? (
          <div className="flex min-h-[22rem] flex-col items-center justify-center gap-4 px-6 py-10 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-rose-200 bg-rose-50 text-rose-600 dark:border-rose-800 dark:bg-rose-950/50 dark:text-rose-400">
              <AlertTriangle size={22} />
            </div>
            <div className="max-w-md space-y-1">
              <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                No se pudo reproducir el mini-video
              </h3>
              <p className="break-words text-xs text-slate-600 dark:text-slate-400">{error}</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void startReelGeneration(false)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400"
              >
                <RefreshCw size={13} />
                Reintentar
              </button>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-slate-300 bg-white px-3.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                Cerrar
              </button>
            </div>
          </div>
        ) : currentAct ? (
          <>
            {/* Escenario cinematográfico */}
            <div className="relative flex min-h-[21rem] flex-1 flex-col justify-between overflow-y-auto bg-gradient-to-b from-slate-50 via-white to-slate-50/90 px-5 py-6 sm:min-h-[24rem] sm:px-8 dark:from-slate-900 dark:via-slate-950 dark:to-slate-900/95">
              {/* Etiqueta discreta del acto en la esquina superior */}
              <div className="mb-4 flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white/90 px-2.5 py-0.5 text-[11px] font-semibold text-slate-700 shadow-2xs dark:border-slate-800 dark:bg-slate-900/90 dark:text-slate-200">
                  <span className="h-1.5 w-1.5 rounded-full bg-indigo-500" />
                  Acto {safeActIdx + 1}/{acts.length} · {actKindLabel}
                </span>
                <span className="truncate text-xs font-medium text-slate-500 dark:text-slate-400">
                  {currentAct.title}
                </span>
              </div>

              {/* Escena cinética según tipo de acto */}
              <div
                key={`${reel?.updated_at ?? ''}-${currentAct.index}`}
                className="cinema-act-enter my-auto flex w-full flex-col items-center justify-center py-2"
              >
                <CinemaActStage
                  act={currentAct}
                  actProgress={actProgress}
                  hasEnded={hasEnded}
                  onCloseToGuide={onClose}
                />
              </div>

              {/* Subtítulos cinéticos palabra por palabra */}
              <div className="mt-5 rounded-xl border border-slate-200/90 bg-white/95 px-4 py-3 text-center shadow-xs dark:border-slate-800 dark:bg-slate-900/90">
                <p className="mx-auto max-w-2xl text-sm leading-relaxed sm:text-[15px]">
                  {kineticWords.map((item, idx) => {
                    const isCurrent = idx === activeWordIdx
                    const isSpoken = activeWordIdx >= 0 && idx < activeWordIdx
                    return (
                      <span key={idx}>
                        <span
                          className={`inline-block rounded px-0.5 transition-colors duration-150 ${
                            isCurrent
                              ? 'bg-indigo-100 font-semibold text-indigo-950 dark:bg-indigo-500/35 dark:text-white'
                              : isSpoken
                                ? 'text-slate-900 dark:text-slate-100'
                                : 'text-slate-400 dark:text-slate-500'
                          }`}
                        >
                          {item.word}
                        </span>
                        {idx < kineticWords.length - 1 ? ' ' : ''}
                      </span>
                    )
                  })}
                </p>
              </div>
            </div>

            {/* Barra inferior de controles tipo video */}
            <footer className="flex flex-col gap-3 border-t border-slate-200 bg-slate-50 px-4 py-3 sm:px-5 dark:border-slate-800 dark:bg-slate-900/95">
              {/* Timeline continua clicable con divisores de los 5 actos */}
              <div className="flex flex-col gap-1.5">
                <div
                  ref={timelineRef}
                  role="slider"
                  tabIndex={0}
                  aria-label="Línea de tiempo del mini-video"
                  aria-valuemin={0}
                  aria-valuemax={Math.round(totalDuration)}
                  aria-valuenow={Math.round(globalTime)}
                  onClick={handleTimelineClick}
                  onKeyDown={(e) => {
                    if (e.key === 'ArrowRight') {
                      e.preventDefault()
                      jumpToAct(safeActIdx, actTime + 3)
                    } else if (e.key === 'ArrowLeft') {
                      e.preventDefault()
                      jumpToAct(safeActIdx, Math.max(0, actTime - 3))
                    }
                  }}
                  className="group relative h-2.5 w-full cursor-pointer overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"
                >
                  <div
                    className="h-full rounded-full bg-indigo-600 transition-[width] duration-75 dark:bg-indigo-400"
                    style={{ width: `${globalProgress * 100}%` }}
                  />
                  {/* Divisores visuales entre actos */}
                  {acts.slice(1).map((a, idx) => {
                    const offset = actOffsets[idx + 1] ?? 0
                    const pct = totalDuration > 0 ? (offset / totalDuration) * 100 : 0
                    return (
                      <span
                        key={a.index}
                        style={{ left: `${pct}%` }}
                        className="pointer-events-none absolute top-0 h-full w-0.5 bg-white/90 dark:bg-slate-950/90"
                      />
                    )
                  })}
                </div>

                {/* Etiquetas clicables de los 5 actos */}
                <div className="grid grid-cols-5 gap-1">
                  {acts.map((a, idx) => {
                    const active = idx === safeActIdx
                    const passed = idx < safeActIdx || hasEnded
                    const label = ACT_KIND_LABEL[a.kind] ?? `Acto ${idx + 1}`
                    return (
                      <button
                        key={a.index}
                        type="button"
                        onClick={() => jumpToAct(idx, 0)}
                        className={`truncate rounded-md px-1.5 py-1 text-center text-[11px] font-medium transition-colors ${
                          active
                            ? 'bg-indigo-600 text-white dark:bg-indigo-500'
                            : passed
                              ? 'bg-indigo-50 text-indigo-800 hover:bg-indigo-100 dark:bg-indigo-950/50 dark:text-indigo-200 dark:hover:bg-indigo-950'
                              : 'bg-white text-slate-600 hover:bg-slate-100 dark:bg-slate-950/60 dark:text-slate-400 dark:hover:bg-slate-800'
                        }`}
                      >
                        <span className="font-mono text-[10px] opacity-80">{idx + 1}. </span>
                        {label}
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Controles de reproducción */}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleTogglePlay}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
                  >
                    {isPlaying ? <Pause size={14} /> : <Play size={14} />}
                    {isPlaying ? 'Pausa' : hasEnded ? 'Ver de nuevo' : 'Play'}
                  </button>

                  <span className="font-mono text-xs tabular-nums text-slate-600 dark:text-slate-300">
                    {formatTime(globalTime)} / {formatTime(totalDuration)}
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  {/* Velocidad 1x / 1.25x / 1.5x */}
                  <div
                    role="group"
                    aria-label="Velocidad de reproducción"
                    className="inline-flex rounded-lg border border-slate-300 bg-white p-0.5 dark:border-slate-700 dark:bg-slate-950"
                  >
                    {PLAYBACK_RATES.map((r) => (
                      <button
                        key={r}
                        type="button"
                        aria-pressed={playbackRate === r}
                        onClick={() => setPlaybackRate(r)}
                        className={`rounded-md px-2 py-0.5 font-mono text-[11px] font-semibold transition-colors ${
                          playbackRate === r
                            ? 'bg-indigo-600 text-white dark:bg-indigo-500'
                            : 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white'
                        }`}
                      >
                        {r}x
                      </button>
                    ))}
                  </div>

                  <button
                    type="button"
                    onClick={handleRestart}
                    title="Reiniciar desde el acto 1"
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-800"
                  >
                    <RotateCcw size={13} />
                    Reiniciar
                  </button>

                  <button
                    type="button"
                    onClick={() => void startReelGeneration(true)}
                    title="Regenerar guion y narración del mini-video"
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-800"
                  >
                    <RefreshCw size={13} />
                    Regenerar video
                  </button>
                </div>
              </div>
            </footer>
          </>
        ) : null}
      </div>
    </div>
  )
}

// ============================================================================
// Escenarios cinéticos visuales por acto (sin muros de texto)
// ============================================================================

function CinemaActStage({
  act,
  actProgress,
  hasEnded,
  onCloseToGuide,
}: {
  act: CinemaAct
  actProgress: number
  hasEnded: boolean
  onCloseToGuide: () => void
}) {
  switch (act.kind) {
    case 'hook':
      return <HookScene act={act} actProgress={actProgress} />
    case 'analogy':
      return <AnalogyScene act={act} actProgress={actProgress} />
    case 'mechanism':
      return <MechanismScene act={act} actProgress={actProgress} />
    case 'payoff':
      return <PayoffScene act={act} actProgress={actProgress} />
    case 'takeaway':
      return (
        <TakeawayScene
          act={act}
          actProgress={actProgress}
          hasEnded={hasEnded}
          onCloseToGuide={onCloseToGuide}
        />
      )
    default:
      return <AnalogyScene act={act} actProgress={actProgress} />
  }
}

function VisualNodeCard({
  node,
  highlighted,
  delayMs = 0,
  extraClass = '',
}: {
  node: CinemaVisualNode
  highlighted: boolean
  delayMs?: number
  extraClass?: string
}) {
  const styles = getToneClasses(node.tone, node.status)
  const badge = statusBadgeText(node.status)
  return (
    <div
      style={{ animationDelay: `${delayMs}ms` }}
      className={`cinema-card-pop flex flex-col gap-1.5 rounded-xl border p-4 shadow-xs transition-all duration-300 ${
        styles.card
      } ${highlighted ? `${styles.ring} scale-[1.02]` : 'opacity-90'} ${extraClass}`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={`inline-flex items-center gap-1.5 ${styles.accent}`}>
          <StatusIcon status={node.status} />
          <span className="text-sm font-bold tracking-tight">{node.label}</span>
        </span>
        {badge && (
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${styles.badge}`}>
            {badge}
          </span>
        )}
      </div>
      {node.sublabel && (
        <p className="text-xs leading-snug opacity-85">{node.sublabel}</p>
      )}
    </div>
  )
}

function AnimatedSvgConnector({ active }: { active: boolean }) {
  return (
    <div className="hidden shrink-0 items-center justify-center sm:flex" aria-hidden="true">
      <svg width="44" height="24" viewBox="0 0 44 24" fill="none">
        <path
          d="M2 12H36"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          className={
            active
              ? 'cinema-dash-flow text-indigo-500 dark:text-indigo-400'
              : 'text-slate-300 dark:text-slate-700'
          }
        />
        <path
          d="M31 7L37 12L31 17"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={
            active
              ? 'text-indigo-600 dark:text-indigo-400'
              : 'text-slate-300 dark:text-slate-700'
          }
        />
        {active && (
          <circle
            cx="20"
            cy="12"
            r="3.5"
            className="cinema-pulse-dot fill-indigo-500 dark:fill-indigo-400"
          />
        )}
      </svg>
    </div>
  )
}

function HookScene({ act, actProgress }: { act: CinemaAct; actProgress: number }) {
  const contrastNodes = act.nodes.slice(0, 2)
  return (
    <div className="flex w-full max-w-3xl flex-col items-center gap-5">
      <h3 className="max-w-2xl text-center text-xl font-bold tracking-tight text-slate-900 sm:text-2xl dark:text-white">
        {act.headline || act.title}
      </h3>

      {contrastNodes.length > 0 && (
        <div className="grid w-full grid-cols-1 items-stretch gap-3 sm:grid-cols-[1fr_auto_1fr]">
          <VisualNodeCard
            node={contrastNodes[0]}
            highlighted={actProgress < 0.5}
            delayMs={60}
          />
          {contrastNodes[1] ? (
            <>
              <div className="flex items-center justify-center">
                <span className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-slate-200 bg-white text-indigo-600 shadow-2xs dark:border-slate-700 dark:bg-slate-900 dark:text-indigo-400">
                  <ArrowRight size={15} />
                </span>
              </div>
              <VisualNodeCard
                node={contrastNodes[1]}
                highlighted={actProgress >= 0.5}
                delayMs={180}
              />
            </>
          ) : null}
        </div>
      )}

      {act.flow_label && (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-indigo-200 bg-indigo-50/90 px-3 py-1 text-xs font-medium text-indigo-900 dark:border-indigo-800/80 dark:bg-indigo-950/50 dark:text-indigo-200">
          <Zap size={12} className="text-indigo-500" />
          {act.flow_label}
        </span>
      )}
    </div>
  )
}

function AnalogyScene({ act, actProgress }: { act: CinemaAct; actProgress: number }) {
  const nodes = act.nodes.slice(0, 4)
  const activeStep = nodes.length > 0 ? Math.min(nodes.length - 1, Math.floor(actProgress * nodes.length)) : 0

  return (
    <div className="flex w-full max-w-3xl flex-col items-center gap-5">
      <h3 className="max-w-2xl text-center text-lg font-bold tracking-tight text-slate-900 sm:text-xl dark:text-white">
        {act.headline || act.title}
      </h3>

      {nodes.length > 0 && (
        <div className="flex w-full flex-col items-stretch justify-center gap-3 sm:flex-row sm:items-center">
          {nodes.map((node, idx) => (
            <div key={node.id || idx} className="flex flex-1 items-center gap-2">
              <div className="w-full">
                <VisualNodeCard
                  node={node}
                  highlighted={idx <= activeStep}
                  delayMs={idx * 100}
                />
              </div>
              {idx < nodes.length - 1 && <AnimatedSvgConnector active={idx < activeStep || actProgress > 0.15} />}
            </div>
          ))}
        </div>
      )}

      {act.flow_label && (
        <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3.5 py-1 text-xs font-medium text-slate-700 shadow-2xs dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
          <ArrowRight size={13} className="text-indigo-500" />
          {act.flow_label}
        </div>
      )}
    </div>
  )
}

function MechanismScene({ act, actProgress }: { act: CinemaAct; actProgress: number }) {
  const hasCodeMorph =
    act.visual_mode === 'code_morph' &&
    Boolean(act.code_before?.trim()) &&
    Boolean(act.code_after?.trim())

  if (hasCodeMorph) {
    const showAfterFocus = actProgress >= 0.45
    return (
      <div className="flex w-full max-w-3xl flex-col items-center gap-4">
        <div className="flex flex-col items-center gap-1.5 text-center">
          <h3 className="text-lg font-bold tracking-tight text-slate-900 sm:text-xl dark:text-white">
            {act.headline || act.title}
          </h3>
          {act.flow_label && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-0.5 text-[11px] font-semibold text-indigo-800 dark:border-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-200">
              <Cpu size={12} />
              {act.flow_label}
            </span>
          )}
        </div>

        <div className="grid w-full grid-cols-1 items-stretch gap-3 md:grid-cols-[1fr_auto_1fr]">
          {/* Antes */}
          <div
            className={`flex flex-col overflow-hidden rounded-xl border transition-all duration-500 ${
              !showAfterFocus
                ? 'border-amber-400 bg-amber-50/70 ring-2 ring-amber-400/35 dark:border-amber-600 dark:bg-amber-950/30'
                : 'border-rose-200 bg-rose-50/40 opacity-75 dark:border-rose-900/70 dark:bg-rose-950/20'
            }`}
          >
            <div className="flex items-center justify-between border-b border-amber-200/80 bg-amber-100/70 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-amber-900 dark:border-amber-800/70 dark:bg-amber-950/60 dark:text-amber-200">
              <span>Antes</span>
              <AlertTriangle size={12} />
            </div>
            <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed text-slate-900 dark:text-slate-100">
              {act.code_before}
            </pre>
          </div>

          <div className="flex items-center justify-center">
            <AnimatedSvgConnector active={true} />
            <ArrowRight
              size={18}
              className="text-indigo-500 sm:hidden"
            />
          </div>

          {/* Después */}
          <div
            className={`flex flex-col overflow-hidden rounded-xl border transition-all duration-500 ${
              showAfterFocus
                ? 'scale-[1.01] border-emerald-500 bg-emerald-50/80 ring-2 ring-emerald-500/40 dark:border-emerald-500 dark:bg-emerald-950/35'
                : 'border-slate-200 bg-slate-50/60 opacity-70 dark:border-slate-800 dark:bg-slate-900/50'
            }`}
          >
            <div className="flex items-center justify-between border-b border-emerald-200/80 bg-emerald-100/70 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-emerald-900 dark:border-emerald-800/70 dark:bg-emerald-950/60 dark:text-emerald-200">
              <span>Después</span>
              <CheckCircle2 size={12} />
            </div>
            <pre className="overflow-x-auto p-3 font-mono text-xs leading-relaxed text-slate-900 dark:text-slate-100">
              {act.code_after}
            </pre>
          </div>
        </div>
      </div>
    )
  }

  // Modo kinetic_blocks con señal animada viajando entre piezas
  const nodes = act.nodes.slice(0, 4)
  const signalIdx =
    nodes.length > 0 ? Math.min(nodes.length - 1, Math.floor(actProgress * nodes.length)) : 0

  return (
    <div className="flex w-full max-w-3xl flex-col items-center gap-5">
      <h3 className="max-w-2xl text-center text-lg font-bold tracking-tight text-slate-900 sm:text-xl dark:text-white">
        {act.headline || act.title}
      </h3>

      {nodes.length > 0 && (
        <div className="flex w-full flex-col items-stretch justify-center gap-3 sm:flex-row sm:items-center">
          {nodes.map((node, idx) => (
            <div key={node.id || idx} className="flex flex-1 items-center gap-2">
              <div className="relative w-full">
                <VisualNodeCard
                  node={node}
                  highlighted={idx === signalIdx}
                  delayMs={idx * 90}
                />
                {idx === signalIdx && (
                  <span className="cinema-pulse-dot absolute -top-2 right-3 inline-flex h-4 w-4 items-center justify-center rounded-full bg-indigo-600 text-white shadow-xs dark:bg-indigo-400 dark:text-slate-950">
                    <Zap size={9} />
                  </span>
                )}
              </div>
              {idx < nodes.length - 1 && (
                <AnimatedSvgConnector active={idx === signalIdx || idx < signalIdx} />
              )}
            </div>
          ))}
        </div>
      )}

      {act.flow_label && (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-indigo-200 bg-indigo-50 px-3.5 py-1 text-xs font-medium text-indigo-900 dark:border-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-200">
          <Cpu size={13} className="text-indigo-500" />
          {act.flow_label}
        </span>
      )}
    </div>
  )
}

function PayoffScene({ act, actProgress }: { act: CinemaAct; actProgress: number }) {
  const coreNode =
    act.nodes.find((n) => (n.status || '').toLowerCase() === 'core') ?? act.nodes[0]
  const pluggedNodes = act.nodes.filter((n) => n !== coreNode).slice(0, 2)
  const pluggedIn = actProgress >= 0.25

  return (
    <div className="flex w-full max-w-3xl flex-col items-center gap-5">
      <h3 className="max-w-2xl text-center text-lg font-bold tracking-tight text-slate-900 sm:text-xl dark:text-white">
        {act.headline || act.title}
      </h3>

      {coreNode && (
        <div className="grid w-full grid-cols-1 items-center gap-3 sm:grid-cols-[1.1fr_auto_1fr]">
          {/* Núcleo estable protegido */}
          <div className="rounded-2xl border-2 border-indigo-400/90 bg-indigo-50/70 p-4 shadow-sm dark:border-indigo-500/80 dark:bg-indigo-950/40">
            <div className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 text-sm font-bold text-indigo-950 dark:text-indigo-100">
                <Shield size={16} className="text-indigo-600 dark:text-indigo-400" />
                {coreNode.label}
              </span>
              <span className="rounded-full bg-indigo-600 px-2 py-0.5 text-[10px] font-semibold text-white dark:bg-indigo-500">
                Estable
              </span>
            </div>
            {coreNode.sublabel && (
              <p className="mt-1.5 text-xs text-indigo-900/85 dark:text-indigo-200/85">
                {coreNode.sublabel}
              </p>
            )}
          </div>

          <div className="flex items-center justify-center">
            <AnimatedSvgConnector active={pluggedIn} />
          </div>

          {/* Tarjetas nuevas/resueltas enchufándose en esmeralda */}
          <div className="flex flex-col gap-2.5">
            {pluggedNodes.length > 0 ? (
              pluggedNodes.map((pNode, idx) => (
                <div
                  key={pNode.id || idx}
                  style={{ animationDelay: `${160 + idx * 140}ms` }}
                  className={`cinema-plug-in rounded-xl border border-emerald-400/90 bg-emerald-50/85 p-3.5 text-emerald-950 shadow-xs transition-all dark:border-emerald-600/80 dark:bg-emerald-950/40 dark:text-emerald-100 ${
                    pluggedIn ? 'ring-2 ring-emerald-500/35' : 'opacity-80'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 text-sm font-bold">
                      <Sparkles size={14} className="text-emerald-600 dark:text-emerald-400" />
                      {pNode.label}
                    </span>
                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800 dark:bg-emerald-900/70 dark:text-emerald-200">
                      {statusBadgeText(pNode.status) ?? 'Integrado'}
                    </span>
                  </div>
                  {pNode.sublabel && (
                    <p className="mt-1 text-xs opacity-85">{pNode.sublabel}</p>
                  )}
                </div>
              ))
            ) : (
              <div className="cinema-plug-in rounded-xl border border-emerald-400/90 bg-emerald-50/85 p-3.5 text-xs font-medium text-emerald-900 dark:border-emerald-600/80 dark:bg-emerald-950/40 dark:text-emerald-200">
                Sistema extensible sin romper el núcleo existente.
              </div>
            )}
          </div>
        </div>
      )}

      {act.flow_label && (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3.5 py-1 text-xs font-medium text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-200">
          <CheckCircle2 size={13} className="text-emerald-600 dark:text-emerald-400" />
          {act.flow_label}
        </span>
      )}
    </div>
  )
}

function TakeawayScene({
  act,
  actProgress,
  hasEnded,
  onCloseToGuide,
}: {
  act: CinemaAct
  actProgress: number
  hasEnded: boolean
  onCloseToGuide: () => void
}) {
  const pills = (act.pills ?? []).filter((p) => p.trim().length > 0).slice(0, 3)

  return (
    <div className="flex w-full max-w-2xl flex-col items-center gap-5">
      <h3 className="text-center text-xl font-bold tracking-tight text-slate-900 sm:text-2xl dark:text-white">
        {act.headline || '3 claves para recordar'}
      </h3>

      {pills.length > 0 && (
        <div className="flex w-full flex-col gap-2.5">
          {pills.map((pill, idx) => {
            const threshold = idx === 0 ? 0 : idx === 1 ? 0.28 : 0.56
            const revealed = hasEnded || actProgress >= threshold
            return (
              <div
                key={idx}
                className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-left transition-all duration-400 ${
                  revealed
                    ? 'translate-y-0 border-indigo-300 bg-indigo-50/80 text-slate-900 opacity-100 shadow-xs dark:border-indigo-700/80 dark:bg-indigo-950/45 dark:text-slate-100'
                    : 'translate-y-2 border-slate-200 bg-slate-100/60 text-slate-400 opacity-40 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-600'
                }`}
              >
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-mono text-xs font-bold ${
                    revealed
                      ? 'bg-indigo-600 text-white dark:bg-indigo-500'
                      : 'bg-slate-300 text-slate-600 dark:bg-slate-800 dark:text-slate-500'
                  }`}
                >
                  {idx + 1}
                </span>
                <span className="text-sm font-semibold leading-snug">{pill}</span>
              </div>
            )
          })}
        </div>
      )}

      <button
        type="button"
        onClick={onCloseToGuide}
        className={`mt-1 inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold transition-all ${
          hasEnded
            ? 'bg-emerald-600 text-white shadow-md ring-4 ring-emerald-500/25 hover:bg-emerald-500 dark:bg-emerald-500 dark:text-slate-950 dark:hover:bg-emerald-400'
            : 'bg-indigo-600 text-white shadow-sm hover:bg-indigo-500 dark:bg-indigo-500 dark:hover:bg-indigo-400'
        }`}
      >
        Ir a la guía y código
        <ArrowRight size={16} />
      </button>
    </div>
  )
}
