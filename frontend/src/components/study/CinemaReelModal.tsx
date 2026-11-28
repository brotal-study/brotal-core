import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Code2,
  Film,
  Layers,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Shield,
  Sparkles,
  Subtitles,
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

const PLAYBACK_RATES = [1, 1.25, 1.5] as const
type PlaybackRate = (typeof PLAYBACK_RATES)[number]

const FALLBACK_REVEAL_SLOTS = [0.12, 0.38, 0.64, 0.8] as const

const DEFAULT_EDITORIAL_KICKERS: Record<CinemaActKind, string> = {
  hook: '// el problema',
  analogy: '// el truco',
  mechanism: '// por dentro',
  payoff: '// el resultado',
  takeaway: '// quédate con esto',
}

const FORBIDDEN_KICKER_TOKENS = new Set([
  'acto',
  'gancho',
  'analogia',
  'mecanismo',
  'impacto',
  'claves',
  'hook',
  'analogy',
  'mechanism',
  'payoff',
  'takeaway',
])

const ACCENT_STOPWORDS = new Set([
  'el',
  'la',
  'los',
  'las',
  'un',
  'una',
  'unos',
  'unas',
  'de',
  'del',
  'al',
  'a',
  'en',
  'con',
  'por',
  'para',
  'sin',
  'sobre',
  'y',
  'o',
  'u',
  'e',
  'que',
  'como',
  'su',
  'sus',
  'tu',
  'tus',
  'se',
  'es',
  'son',
  'no',
  'mas',
  'pero',
  'si',
  'esta',
  'este',
  'todo',
  'cada',
])

interface ActTheme {
  text: string
  barFill: string
  glowRgba: string
  borderActive: string
  dot: string
  pillBg: string
  ctaBg: string
}

const ACT_THEME_BY_KIND: Record<CinemaActKind, ActTheme> = {
  hook: {
    text: 'text-amber-400',
    barFill: 'bg-amber-400',
    glowRgba: 'rgba(245, 158, 11, 0.13)',
    borderActive: 'border-amber-400/55 bg-amber-400/[0.07] shadow-[0_0_28px_-10px_rgba(245,158,11,0.45)]',
    dot: 'bg-amber-400',
    pillBg: 'border-amber-400/35 bg-amber-400/10 text-amber-200',
    ctaBg: 'bg-amber-400 text-slate-950 hover:bg-amber-300',
  },
  analogy: {
    text: 'text-sky-400',
    barFill: 'bg-sky-400',
    glowRgba: 'rgba(56, 189, 248, 0.13)',
    borderActive: 'border-sky-400/55 bg-sky-400/[0.07] shadow-[0_0_28px_-10px_rgba(56,189,248,0.45)]',
    dot: 'bg-sky-400',
    pillBg: 'border-sky-400/35 bg-sky-400/10 text-sky-200',
    ctaBg: 'bg-sky-400 text-slate-950 hover:bg-sky-300',
  },
  mechanism: {
    text: 'text-indigo-400',
    barFill: 'bg-indigo-400',
    glowRgba: 'rgba(99, 102, 241, 0.15)',
    borderActive: 'border-indigo-400/55 bg-indigo-400/[0.08] shadow-[0_0_28px_-10px_rgba(99,102,241,0.5)]',
    dot: 'bg-indigo-400',
    pillBg: 'border-indigo-400/35 bg-indigo-400/10 text-indigo-200',
    ctaBg: 'bg-indigo-400 text-slate-950 hover:bg-indigo-300',
  },
  payoff: {
    text: 'text-emerald-400',
    barFill: 'bg-emerald-400',
    glowRgba: 'rgba(16, 185, 129, 0.14)',
    borderActive: 'border-emerald-400/55 bg-emerald-400/[0.07] shadow-[0_0_28px_-10px_rgba(16,185,129,0.45)]',
    dot: 'bg-emerald-400',
    pillBg: 'border-emerald-400/35 bg-emerald-400/10 text-emerald-200',
    ctaBg: 'bg-emerald-400 text-slate-950 hover:bg-emerald-300',
  },
  takeaway: {
    text: 'text-lime-400',
    barFill: 'bg-lime-400',
    glowRgba: 'rgba(163, 230, 53, 0.13)',
    borderActive: 'border-lime-400/55 bg-lime-400/[0.07] shadow-[0_0_28px_-10px_rgba(163,230,53,0.45)]',
    dot: 'bg-lime-400',
    pillBg: 'border-lime-400/35 bg-lime-400/10 text-lime-200',
    ctaBg: 'bg-lime-400 text-slate-950 hover:bg-lime-300',
  },
}

interface NodeToneStyle {
  icon: string
  activeBorder: string
  dot: string
}

function getNodeToneStyle(tone: string, status?: string): NodeToneStyle {
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
          : 'sky')

  switch (resolved) {
    case 'rose':
      return {
        icon: 'text-rose-400',
        activeBorder: 'border-rose-400/55 bg-rose-500/[0.08] shadow-[0_0_26px_-10px_rgba(244,63,94,0.5)]',
        dot: 'bg-rose-400',
      }
    case 'emerald':
      return {
        icon: 'text-emerald-400',
        activeBorder: 'border-emerald-400/55 bg-emerald-500/[0.08] shadow-[0_0_26px_-10px_rgba(16,185,129,0.5)]',
        dot: 'bg-emerald-400',
      }
    case 'amber':
      return {
        icon: 'text-amber-400',
        activeBorder: 'border-amber-400/55 bg-amber-500/[0.08] shadow-[0_0_26px_-10px_rgba(245,158,11,0.5)]',
        dot: 'bg-amber-400',
      }
    case 'sky':
      return {
        icon: 'text-sky-400',
        activeBorder: 'border-sky-400/55 bg-sky-500/[0.08] shadow-[0_0_26px_-10px_rgba(56,189,248,0.5)]',
        dot: 'bg-sky-400',
      }
    case 'indigo':
      return {
        icon: 'text-indigo-400',
        activeBorder: 'border-indigo-400/55 bg-indigo-500/[0.09] shadow-[0_0_26px_-10px_rgba(99,102,241,0.5)]',
        dot: 'bg-indigo-400',
      }
    default:
      return {
        icon: 'text-slate-300',
        activeBorder: 'border-white/35 bg-white/[0.06] shadow-[0_0_24px_-10px_rgba(255,255,255,0.25)]',
        dot: 'bg-slate-300',
      }
  }
}

function NodeGlyph({ status, className }: { status: string; className?: string }) {
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

function normalizeToken(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '')
}

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
      return 'Diseñando guion editorial...'
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

function resolveEditorialKicker(act: CinemaAct): string {
  const fallback = DEFAULT_EDITORIAL_KICKERS[act.kind] ?? '// idea clave'
  const raw = (act.kicker || '').trim()
  if (!raw) return fallback
  const stripped = raw.replace(/^\/+\s*/, '').trim()
  if (!stripped) return fallback
  const tokens = stripped
    .split(/\s+/)
    .map((t) => normalizeToken(t))
    .filter(Boolean)
  if (tokens.length === 0 || tokens.some((t) => FORBIDDEN_KICKER_TOKENS.has(t))) {
    return fallback
  }
  return `// ${stripped.toLowerCase()}`
}

function resolvePreviousEcho(act: CinemaAct, prevAct?: CinemaAct): string {
  if (act.index <= 0 || !prevAct) return ''
  const raw = (act.previous_echo || '').trim()
  if (raw) return raw
  const prevHeadline = (prevAct.headline || prevAct.title || '')
    .trim()
    .replace(/^[¿¡]+|[?!.]+$/g, '')
  if (!prevHeadline) return ''
  const words = prevHeadline.split(/\s+/).filter(Boolean)
  if (words.length <= 4) return words.join(' ')
  return words.slice(-4).join(' ')
}

function resolveAccentWordSet(act: CinemaAct, headline: string): Set<string> {
  const explicit = (act.accent_words ?? [])
    .flatMap((w) => w.split(/\s+/))
    .map((w) => normalizeToken(w))
    .filter(Boolean)
  if (explicit.length > 0) {
    return new Set(explicit.slice(0, 2))
  }

  const words = headline.trim().split(/\s+/).filter(Boolean)
  const meaningful = words
    .map((w) => normalizeToken(w))
    .filter((t) => t.length >= 4 && !ACCENT_STOPWORDS.has(t))

  if (meaningful.length === 0) {
    const last = words.length > 0 ? normalizeToken(words[words.length - 1]) : ''
    return last ? new Set([last]) : new Set()
  }

  const picked = [meaningful[meaningful.length - 1]]
  if (meaningful.length >= 3) {
    const longestBefore = meaningful
      .slice(0, -1)
      .reduce((best, cur) => (cur.length > best.length ? cur : best), '')
    if (longestBefore && longestBefore !== picked[0]) {
      picked.push(longestBefore)
    }
  }
  return new Set(picked)
}

function resolveNodeRevealAt(node: CinemaVisualNode, idx: number): number {
  if (typeof node.reveal_at === 'number' && Number.isFinite(node.reveal_at)) {
    return clamp(node.reveal_at, 0.04, 0.92)
  }
  return FALLBACK_REVEAL_SLOTS[idx] ?? 0.84
}

function resolveWindowCaption(act: CinemaAct): string {
  const raw = (act.flow_label || '').trim()
  if (!raw || raw.toLowerCase().startsWith('contraste inicial')) {
    return act.visual_mode === 'code_morph' ? 'editor · refactor' : 'modelo · paso a paso'
  }
  return raw
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

interface CaptionChunk {
  startIdx: number
  endIdx: number
  words: WordSpan[]
}

function buildCaptionChunks(words: WordSpan[]): CaptionChunk[] {
  if (words.length === 0) return []
  const chunks: CaptionChunk[] = []
  let cursor = 0

  while (cursor < words.length) {
    const remaining = words.length - cursor
    let size = remaining <= 5 ? remaining : 4

    // Si hay un corte de oración dentro de las palabras 3..5, cierra el chunk ahí
    if (remaining > 5) {
      for (let k = 2; k <= 4 && cursor + k < words.length; k++) {
        if (/[.!?]$/.test(words[cursor + k].word)) {
          size = k + 1
          break
        }
      }
      // Evita dejar 1 o 2 palabras huérfanas al final
      const leftAfter = words.length - (cursor + size)
      if (leftAfter > 0 && leftAfter < 3 && size === 4) {
        size = 3
      }
    }

    const slice = words.slice(cursor, cursor + size)
    chunks.push({
      startIdx: cursor,
      endIdx: cursor + slice.length - 1,
      words: slice,
    })
    cursor += slice.length
  }

  return chunks
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
  const [showCaptions, setShowCaptions] = useState(false)
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

  const acts = useMemo(() => reel?.acts ?? [], [reel])
  const safeActIdx = acts.length > 0 ? clamp(actIdx, 0, acts.length - 1) : 0
  const currentAct: CinemaAct | undefined = acts[safeActIdx]
  const prevAct: CinemaAct | undefined = safeActIdx > 0 ? acts[safeActIdx - 1] : undefined

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

  // Interpolación suave del % de carga
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

  // Loop rAF para sincronizar progreso real de voz, revelación de piezas y subtítulos CC
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

  // Atajos de teclado: Escape cerrar, Space Play/Pausa, Flechas cambiar de escena
  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
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
      if (e.key === ' ' || e.code === 'Space') {
        e.preventDefault()
        handleTogglePlay()
      } else if (e.key === 'ArrowRight' && acts.length > 0 && safeActIdx < acts.length - 1) {
        e.preventDefault()
        jumpToAct(safeActIdx + 1, 0)
      } else if (e.key === 'ArrowLeft' && safeActIdx > 0) {
        e.preventDefault()
        jumpToAct(safeActIdx - 1, 0)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose, handleTogglePlay, jumpToAct, acts.length, safeActIdx])

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

  const kineticWords = useMemo(
    () => buildKineticWords(currentAct?.narration_es ?? ''),
    [currentAct?.narration_es],
  )

  const captionChunks = useMemo(() => buildCaptionChunks(kineticWords), [kineticWords])

  const activeWordIdx = useMemo(() => {
    if (kineticWords.length === 0) return -1
    if (!isPlaying && actTime <= 0.02 && !hasEnded) return 0
    if (hasEnded) return kineticWords.length - 1
    for (let i = 0; i < kineticWords.length; i++) {
      if (actProgress <= kineticWords[i].endRatio) {
        return i
      }
    }
    return kineticWords.length - 1
  }, [kineticWords, isPlaying, actTime, hasEnded, actProgress])

  const activeCaptionChunk = useMemo(() => {
    if (captionChunks.length === 0) return null
    if (activeWordIdx < 0) return captionChunks[0]
    return (
      captionChunks.find((c) => activeWordIdx >= c.startIdx && activeWordIdx <= c.endIdx) ??
      captionChunks[captionChunks.length - 1]
    )
  }, [captionChunks, activeWordIdx])

  if (!open) return null

  const actTheme: ActTheme = currentAct
    ? (ACT_THEME_BY_KIND[currentAct.kind] ?? ACT_THEME_BY_KIND.mechanism)
    : ACT_THEME_BY_KIND.mechanism

  const isOfflineFallback = reel?.provider === 'local_fallback'

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Modo Cine: ${nodeTitle}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-2.5 backdrop-blur-md sm:p-5"
    >
      <style>{`
        @keyframes cinemaWordRise {
          0% { opacity: 0; transform: translateY(14px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        @keyframes cinemaPieceReveal {
          0% { opacity: 0; transform: translateY(14px) scale(0.985); }
          100% { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes cinemaEchoFade {
          0% { opacity: 0; transform: translateY(8px); }
          100% { opacity: 0.3; transform: translateY(0); }
        }
        @keyframes cinemaCodeFade {
          0% { opacity: 0; transform: translateY(6px); }
          100% { opacity: 1; transform: translateY(0); }
        }
        @keyframes cinemaDotPulse {
          0%, 100% { transform: scale(1); opacity: 0.75; }
          50% { transform: scale(1.35); opacity: 1; }
        }
        .cinema-word-rise {
          animation: cinemaWordRise 460ms cubic-bezier(0.22, 1, 0.36, 1) both;
        }
        .cinema-piece-reveal {
          animation: cinemaPieceReveal 440ms cubic-bezier(0.22, 1, 0.36, 1) both;
        }
        .cinema-echo-fade {
          animation: cinemaEchoFade 540ms cubic-bezier(0.22, 1, 0.36, 1) both;
        }
        .cinema-code-fade {
          animation: cinemaCodeFade 360ms cubic-bezier(0.22, 1, 0.36, 1) both;
        }
        .cinema-dot-pulse {
          animation: cinemaDotPulse 1.5s ease-in-out infinite;
        }
      `}</style>

      {/* Canvas cinematográfico Widescreen 16:9 */}
      <div className="relative flex max-h-[92vh] w-full max-w-[1140px] flex-col overflow-hidden rounded-2xl bg-[#07090e] text-slate-100 shadow-[0_32px_90px_-15px_rgba(0,0,0,0.9)] ring-1 ring-white/10 lg:aspect-video">
        {/* Único resplandor radial sutil del color acento del acto */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 transition-all duration-700"
          style={{
            background: `radial-gradient(ellipse 68% 58% at 72% 46%, ${actTheme.glowRgba}, transparent 72%)`,
          }}
        />

        {/* Barra superior minimalista tipo Stories */}
        <header className="relative z-10 flex flex-col gap-2 px-4 pt-3 pb-1 sm:px-6 sm:pt-4">
          {/* 5 barras delgadas continuas clicables (sin etiquetas meta) */}
          {acts.length > 0 && !loading && !error && (
            <div
              className="grid gap-1.5"
              style={{ gridTemplateColumns: `repeat(${acts.length}, minmax(0, 1fr))` }}
            >
              {acts.map((act, idx) => {
                const fillPct =
                  hasEnded || idx < safeActIdx
                    ? 100
                    : idx === safeActIdx
                      ? clamp(actProgress * 100, 0, 100)
                      : 0
                return (
                  <button
                    key={act.index}
                    type="button"
                    onClick={() => jumpToAct(idx, 0)}
                    aria-label={`Ir a la escena ${idx + 1}`}
                    className="group py-1.5 text-left focus:outline-none"
                  >
                    <span className="block h-[3px] w-full overflow-hidden rounded-full bg-white/15 transition-colors group-hover:bg-white/25">
                      <span
                        className={`block h-full rounded-full transition-[width] duration-75 ${
                          idx === safeActIdx ? actTheme.barFill : 'bg-white/80'
                        }`}
                        style={{ width: `${fillPct}%` }}
                      />
                    </span>
                  </button>
                )
              })}
            </div>
          )}

          {/* Título discreto del tema + botón cerrar */}
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <Film size={13} className="shrink-0 text-white/40" />
              <h2 className="truncate text-xs font-medium tracking-wide text-white/50">
                {reel?.title || nodeTitle}
              </h2>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              {visualOnlyMode && !loading && !error && (
                <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-0.5 text-[11px] font-medium text-white/65">
                  <VolumeX size={11} />
                  Modo visual
                </span>
              )}
              <button
                type="button"
                onClick={onClose}
                aria-label="Cerrar Modo Cine"
                className="inline-flex h-8 w-8 items-center justify-center rounded-full text-white/55 transition-colors hover:bg-white/10 hover:text-white"
              >
                <X size={16} />
              </button>
            </div>
          </div>
        </header>

        {/* Cuerpo principal: Carga, Error o Escenario Editorial 16:9 */}
        {loading ? (
          <div className="relative z-10 flex min-h-[24rem] flex-1 flex-col items-center justify-center gap-5 px-6 py-10">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04] text-indigo-400">
              <Loader2 size={22} className="animate-spin" />
            </div>

            <div className="w-full max-w-md text-center">
              <div className="flex items-center justify-between gap-2 text-xs font-medium text-white/80">
                <span className="truncate">
                  {progress?.label?.trim() || defaultStageLabel(progress?.stage)}
                </span>
                <span className="font-mono font-semibold tabular-nums text-indigo-400">
                  {clamp(displayPct, 0, 100)}%
                </span>
              </div>

              <div className="mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-indigo-400 transition-all duration-300 ease-out"
                  style={{ width: `${clamp(displayPct, 4, 100)}%` }}
                />
              </div>

              <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-[11px]">
                {(
                  [
                    { id: 'analyzing', text: 'Analizando concepto' },
                    { id: 'scripting', text: 'Guion editorial' },
                    { id: 'synthesizing_audio', text: 'Voz neural' },
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
                      className={`rounded-full px-2.5 py-0.5 font-medium transition-colors ${
                        current
                          ? 'bg-indigo-500/25 text-indigo-200 ring-1 ring-indigo-400/40'
                          : done
                            ? 'bg-emerald-500/15 text-emerald-300'
                            : 'bg-white/[0.04] text-white/40'
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
              className="rounded-lg border border-white/15 bg-white/[0.04] px-4 py-1.5 text-xs font-medium text-white/75 transition-colors hover:bg-white/10 hover:text-white"
            >
              Cancelar
            </button>
          </div>
        ) : error ? (
          <div className="relative z-10 flex min-h-[24rem] flex-1 flex-col items-center justify-center gap-4 px-6 py-10 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-rose-500/30 bg-rose-500/10 text-rose-400">
              <AlertTriangle size={22} />
            </div>
            <div className="max-w-md space-y-1">
              <h3 className="text-sm font-semibold text-white">
                No se pudo reproducir el mini-video
              </h3>
              <p className="break-words text-xs text-white/55">{error}</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void startReelGeneration(false)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 px-3.5 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-indigo-400"
              >
                <RefreshCw size={13} />
                Reintentar
              </button>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-white/15 bg-white/[0.04] px-3.5 py-1.5 text-xs font-medium text-white/75 transition-colors hover:bg-white/10 hover:text-white"
              >
                Cerrar
              </button>
            </div>
          </div>
        ) : currentAct ? (
          <>
            {/* Escenario Editorial Principal */}
            <div className="relative z-10 flex min-h-[22rem] flex-1 flex-col justify-center overflow-y-auto px-5 py-5 sm:px-9 sm:py-6">
              <div
                key={`${reel?.updated_at ?? ''}-${currentAct.index}`}
                className="my-auto w-full"
              >
                {currentAct.kind === 'takeaway' || safeActIdx === acts.length - 1 ? (
                  <TakeawayEditorialStage
                    act={currentAct}
                    prevAct={prevAct}
                    theme={actTheme}
                    actProgress={actProgress}
                    hasEnded={hasEnded}
                    onCloseToGuide={onClose}
                  />
                ) : (
                  <EditorialTwoColumnStage
                    act={currentAct}
                    prevAct={prevAct}
                    theme={actTheme}
                    actProgress={actProgress}
                    hasEnded={hasEnded}
                    isPlaying={isPlaying}
                  />
                )}
              </div>

              {/* Subtítulos CC opcionales: SOLO 1 línea con el chunk actual de 3..5 palabras */}
              {showCaptions && activeCaptionChunk && (
                <div className="pointer-events-none sticky bottom-1 mt-4 flex justify-center">
                  <div className="max-w-[92%] truncate whitespace-nowrap rounded-full border border-white/10 bg-black/75 px-4 py-1.5 text-sm font-medium tracking-tight text-white/90 shadow-lg backdrop-blur-md">
                    {activeCaptionChunk.words.map((span, offset) => {
                      const wordGlobalIdx = activeCaptionChunk.startIdx + offset
                      const isCurrent = wordGlobalIdx === activeWordIdx
                      return (
                        <span key={wordGlobalIdx}>
                          <span
                            className={
                              isCurrent
                                ? `${actTheme.text} font-semibold`
                                : 'text-white/85'
                            }
                          >
                            {span.word}
                          </span>
                          {offset < activeCaptionChunk.words.length - 1 ? ' ' : ''}
                        </span>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>

            {/* Barra inferior de controles compacta y discreta */}
            <footer className="relative z-10 flex flex-wrap items-center justify-between gap-2.5 border-t border-white/[0.07] bg-[#07090e]/95 px-4 py-2.5 sm:px-6">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={handleTogglePlay}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-950 transition-colors hover:bg-slate-200"
                >
                  {isPlaying ? <Pause size={13} /> : <Play size={13} />}
                  {isPlaying ? 'Pausa' : hasEnded ? 'Ver de nuevo' : 'Play'}
                </button>

                <span className="font-mono text-xs tabular-nums text-white/55">
                  {formatTime(globalTime)} / {formatTime(totalDuration)}
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                {isOfflineFallback && (
                  <button
                    type="button"
                    onClick={() => void startReelGeneration(true)}
                    title="Este guion se generó sin IA activa. Haz clic para regenerar."
                    className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/25 bg-amber-400/10 px-2.5 py-1 text-[11px] font-medium text-amber-300 transition-colors hover:bg-amber-400/20"
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                    Guion offline
                  </button>
                )}

                {/* Velocidad 1x / 1.25x / 1.5x */}
                <div
                  role="group"
                  aria-label="Velocidad de reproducción"
                  className="inline-flex rounded-lg border border-white/10 bg-white/[0.03] p-0.5"
                >
                  {PLAYBACK_RATES.map((r) => (
                    <button
                      key={r}
                      type="button"
                      aria-pressed={playbackRate === r}
                      onClick={() => setPlaybackRate(r)}
                      className={`rounded-md px-2 py-0.5 font-mono text-[11px] font-semibold transition-colors ${
                        playbackRate === r
                          ? 'bg-white/15 text-white'
                          : 'text-white/50 hover:text-white/85'
                      }`}
                    >
                      {r}x
                    </button>
                  ))}
                </div>

                {/* Toggle CC (desactivado por defecto) */}
                <button
                  type="button"
                  aria-pressed={showCaptions}
                  onClick={() => setShowCaptions((prev) => !prev)}
                  title={showCaptions ? 'Ocultar subtítulos' : 'Mostrar subtítulos breves (CC)'}
                  className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
                    showCaptions
                      ? 'border-white/30 bg-white/15 text-white'
                      : 'border-white/10 bg-white/[0.03] text-white/55 hover:bg-white/[0.08] hover:text-white'
                  }`}
                >
                  <Subtitles size={13} />
                  CC
                </button>

                <button
                  type="button"
                  onClick={handleRestart}
                  title="Reiniciar desde el principio"
                  className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-xs font-medium text-white/65 transition-colors hover:bg-white/[0.08] hover:text-white"
                >
                  <RotateCcw size={13} />
                  <span className="hidden sm:inline">Reiniciar</span>
                </button>

                <button
                  type="button"
                  onClick={() => void startReelGeneration(true)}
                  title="Regenerar guion y narración del mini-video"
                  className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-xs font-medium text-white/65 transition-colors hover:bg-white/[0.08] hover:text-white"
                >
                  <RefreshCw size={13} />
                  <span className="hidden sm:inline">Regenerar</span>
                </button>
              </div>
            </footer>
          </>
        ) : null}
      </div>
    </div>
  )
}

// ============================================================================
// Tipografía Kinética Editorial + Ventana Flotante Progresiva
// ============================================================================

function KineticHeadline({
  headline,
  accentSet,
  accentClass,
  centered = false,
}: {
  headline: string
  accentSet: Set<string>
  accentClass: string
  centered?: boolean
}) {
  const words = headline.trim().split(/\s+/).filter(Boolean)
  return (
    <h3
      className={`text-3xl font-black leading-[1.05] tracking-tight text-white sm:text-4xl lg:text-5xl ${
        centered ? 'text-center' : 'text-left'
      }`}
    >
      {words.map((word, idx) => {
        const isAccent = accentSet.has(normalizeToken(word))
        return (
          <span
            key={`${word}-${idx}`}
            style={{ animationDelay: `${idx * 65}ms` }}
            className={`cinema-word-rise inline-block ${isAccent ? accentClass : 'text-white'}`}
          >
            {word}
            {idx < words.length - 1 ? '\u00A0' : ''}
          </span>
        )
      })}
    </h3>
  )
}

function EditorialTwoColumnStage({
  act,
  prevAct,
  theme,
  actProgress,
  hasEnded,
  isPlaying,
}: {
  act: CinemaAct
  prevAct?: CinemaAct
  theme: ActTheme
  actProgress: number
  hasEnded: boolean
  isPlaying: boolean
}) {
  const headline = (act.headline || act.title || '').trim()
  const kicker = resolveEditorialKicker(act)
  const previousEcho = resolvePreviousEcho(act, prevAct)
  const accentSet = useMemo(() => resolveAccentWordSet(act, headline), [act, headline])
  const windowCaption = resolveWindowCaption(act)

  const hasCodeMorph =
    act.visual_mode === 'code_morph' &&
    Boolean(act.code_before?.trim()) &&
    Boolean(act.code_after?.trim())

  return (
    <div className="grid w-full grid-cols-1 items-center gap-7 lg:grid-cols-12 lg:gap-10">
      {/* Columna Izquierda: Tipografía Kinética */}
      <div className="flex flex-col justify-center gap-3.5 lg:col-span-5">
        {previousEcho && (
          <p className="cinema-echo-fade select-none text-xs font-medium tracking-tight text-white/30 blur-[0.35px] sm:text-sm">
            {previousEcho}
          </p>
        )}

        <span className={`font-mono text-xs font-semibold tracking-wide sm:text-sm ${theme.text}`}>
          {kicker}
        </span>

        <KineticHeadline
          headline={headline}
          accentSet={accentSet}
          accentClass={theme.text}
        />
      </div>

      {/* Columna Derecha: Ventana Flotante Progresiva estilo macOS */}
      <div className="lg:col-span-7">
        <div className="overflow-hidden rounded-2xl border border-white/10 bg-[#0f131c]/95 shadow-2xl">
          {/* Barra superior de ventana macOS */}
          <div className="flex items-center justify-between gap-3 border-b border-white/[0.07] bg-white/[0.02] px-4 py-2.5">
            <div className="flex items-center gap-1.5" aria-hidden="true">
              <span className="h-2.5 w-2.5 rounded-full bg-white/20" />
              <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
              <span className="h-2.5 w-2.5 rounded-full bg-white/10" />
            </div>
            <span className="truncate font-mono text-[11px] tracking-wide text-white/45">
              {windowCaption}
            </span>
            <span className="w-8 shrink-0" aria-hidden="true" />
          </div>

          {/* Contenido de la ventana: Code Morph o Piezas Progresivas */}
          <div className="min-h-[230px] p-4 sm:min-h-[268px] sm:p-5">
            {hasCodeMorph ? (
              <CodeMorphPanel
                codeBefore={act.code_before || ''}
                codeAfter={act.code_after || ''}
                actProgress={actProgress}
                hasEnded={hasEnded}
                theme={theme}
              />
            ) : (
              <ProgressiveNodesPanel
                nodes={act.nodes.slice(0, 4)}
                actProgress={actProgress}
                hasEnded={hasEnded}
                isPlaying={isPlaying}
                theme={theme}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function ProgressiveNodesPanel({
  nodes,
  actProgress,
  hasEnded,
  isPlaying,
  theme,
}: {
  nodes: CinemaVisualNode[]
  actProgress: number
  hasEnded: boolean
  isPlaying: boolean
  theme: ActTheme
}) {
  const scheduled = useMemo(
    () =>
      nodes.map((node, idx) => ({
        node,
        idx,
        revealAt: resolveNodeRevealAt(node, idx),
      })),
    [nodes],
  )

  const revealedItems = scheduled.filter(
    (entry) => hasEnded || actProgress >= entry.revealAt,
  )
  const latestRevealedIdx =
    revealedItems.length > 0 ? revealedItems[revealedItems.length - 1].idx : -1

  if (revealedItems.length === 0) {
    return (
      <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-2.5 text-center">
        <span className={`cinema-dot-pulse h-2 w-2 rounded-full ${theme.dot}`} />
        <span className="font-mono text-[11px] tracking-wide text-white/35">
          {isPlaying ? 'sincronizando con la voz...' : 'presiona play para comenzar'}
        </span>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2.5">
      {revealedItems.map(({ node, idx }) => {
        const isLatest = !hasEnded && idx === latestRevealedIdx
        const toneStyle = getNodeToneStyle(node.tone, node.status)
        return (
          <div
            key={node.id || idx}
            className={`cinema-piece-reveal flex items-start gap-3.5 rounded-xl border px-4 py-3.5 transition-all duration-300 ${
              isLatest
                ? toneStyle.activeBorder
                : 'border-white/[0.08] bg-white/[0.025]'
            }`}
          >
            <div
              className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] ${toneStyle.icon}`}
            >
              <NodeGlyph status={node.status} />
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-bold tracking-tight text-white sm:text-[15px]">
                  {node.label}
                </p>
                {isLatest && (
                  <span
                    aria-hidden="true"
                    className={`cinema-dot-pulse h-2 w-2 shrink-0 rounded-full ${toneStyle.dot}`}
                  />
                )}
              </div>
              {node.sublabel && (
                <p className="mt-0.5 text-xs leading-snug text-white/60 sm:text-[13px]">
                  {node.sublabel}
                </p>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CodeMorphPanel({
  codeBefore,
  codeAfter,
  actProgress,
  hasEnded,
  theme,
}: {
  codeBefore: string
  codeAfter: string
  actProgress: number
  hasEnded: boolean
  theme: ActTheme
}) {
  const showAfter = hasEnded || actProgress >= 0.48
  const beforeLines = useMemo(() => codeBefore.split('\n'), [codeBefore])
  const afterLines = useMemo(() => codeAfter.split('\n'), [codeAfter])
  const beforeSet = useMemo(
    () => new Set(beforeLines.map((l) => l.trim())),
    [beforeLines],
  )
  const activeLines = showAfter ? afterLines : beforeLines

  return (
    <div className="flex h-full flex-col justify-between gap-4">
      <div className="flex items-center justify-between gap-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[11px] font-medium transition-colors ${
            showAfter
              ? 'border-emerald-400/35 bg-emerald-400/10 text-emerald-300'
              : 'border-amber-400/35 bg-amber-400/10 text-amber-300'
          }`}
        >
          <Code2 size={12} />
          {showAfter ? 'después · diseño limpio' : 'antes · patrón frágil'}
        </span>

        <div className="flex items-center gap-1.5 font-mono text-[10px] text-white/40">
          <span className={!showAfter ? 'text-white/85' : ''}>01</span>
          <span>/</span>
          <span className={showAfter ? 'text-emerald-300' : ''}>02</span>
        </div>
      </div>

      <div
        key={showAfter ? 'after' : 'before'}
        className="cinema-code-fade overflow-x-auto rounded-xl border border-white/[0.07] bg-[#090c12] p-3.5 font-mono text-xs leading-relaxed sm:text-[13px]"
      >
        {activeLines.map((line, idx) => {
          const isImprovedLine = showAfter && !beforeSet.has(line.trim())
          return (
            <div
              key={idx}
              className={`flex gap-3 rounded px-1.5 py-0.5 ${
                isImprovedLine
                  ? 'bg-emerald-400/10 text-emerald-200'
                  : showAfter
                    ? 'text-slate-200'
                    : 'text-amber-100/90'
              }`}
            >
              <span className="w-5 shrink-0 select-none text-right text-white/25">
                {idx + 1}
              </span>
              <span className="whitespace-pre">{line || ' '}</span>
            </div>
          )
        })}
      </div>

      {/* Indicador sutil del morph sincronizado */}
      <div className="h-1 w-full overflow-hidden rounded-full bg-white/[0.07]">
        <div
          className={`h-full rounded-full transition-[width,background-color] duration-150 ${
            showAfter ? 'bg-emerald-400' : theme.barFill
          }`}
          style={{ width: `${clamp(actProgress * 100, 4, 100)}%` }}
        />
      </div>
    </div>
  )
}

function TakeawayEditorialStage({
  act,
  prevAct,
  theme,
  actProgress,
  hasEnded,
  onCloseToGuide,
}: {
  act: CinemaAct
  prevAct?: CinemaAct
  theme: ActTheme
  actProgress: number
  hasEnded: boolean
  onCloseToGuide: () => void
}) {
  const headline = (act.headline || 'Claves para recordar').trim()
  const kicker = resolveEditorialKicker(act)
  const previousEcho = resolvePreviousEcho(act, prevAct)
  const accentSet = useMemo(() => resolveAccentWordSet(act, headline), [act, headline])
  const pills = useMemo(
    () => (act.pills ?? []).filter((p) => p.trim().length > 0).slice(0, 3),
    [act.pills],
  )
  const pillThresholds = [0.08, 0.36, 0.64]

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-6 text-center">
      <div className="flex flex-col items-center gap-3">
        {previousEcho && (
          <p className="cinema-echo-fade select-none text-xs font-medium tracking-tight text-white/30 blur-[0.35px] sm:text-sm">
            {previousEcho}
          </p>
        )}

        <span className={`font-mono text-xs font-semibold tracking-wide sm:text-sm ${theme.text}`}>
          {kicker}
        </span>

        <KineticHeadline
          headline={headline}
          accentSet={accentSet}
          accentClass={theme.text}
          centered
        />
      </div>

      {pills.length > 0 && (
        <div className="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-3">
          {pills.map((pill, idx) => {
            const threshold = pillThresholds[idx] ?? 0.7
            const revealed = hasEnded || actProgress >= threshold
            if (!revealed) {
              return (
                <div
                  key={idx}
                  aria-hidden="true"
                  className="h-[74px] rounded-xl border border-dashed border-white/[0.06] bg-white/[0.01]"
                />
              )
            }
            return (
              <div
                key={idx}
                className="cinema-piece-reveal flex flex-col items-center justify-center gap-1.5 rounded-xl border border-white/10 bg-[#0f131c]/90 px-4 py-3.5 text-center shadow-lg"
              >
                <span className={`font-mono text-[11px] font-bold ${theme.text}`}>
                  0{idx + 1}
                </span>
                <span className="text-sm font-semibold leading-snug text-white">
                  {pill}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {hasEnded && (
        <button
          type="button"
          onClick={onCloseToGuide}
          className={`cinema-piece-reveal mt-1 inline-flex items-center gap-2 rounded-xl px-6 py-3 text-sm font-bold shadow-lg transition-all ${theme.ctaBg}`}
        >
          Ir a la guía y código
          <ArrowRight size={16} />
        </button>
      )}
    </div>
  )
}
