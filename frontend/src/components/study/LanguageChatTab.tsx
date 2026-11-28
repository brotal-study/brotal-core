import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  Award,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  Ear,
  Eye,
  EyeOff,
  Flag,
  GraduationCap,
  HelpCircle,
  Languages,
  Lightbulb,
  Loader2,
  MessageSquare,
  Mic,
  MicOff,
  RotateCcw,
  Send,
  Sparkles,
  Square,
  UserRound,
  Volume2,
  VolumeX,
  Zap,
} from 'lucide-react'
import {
  fetchPhraseTtsBlob,
  PASS_SCORE,
  sendLanguagePracticeChat,
  SttApiError,
  transcribeStudyAudio,
  type LanguageChatMode,
  type LanguageChatSessionSummary,
  type LanguageChatTurn,
  type LanguageSpeakerRole,
  type PackNode,
  type TtsAccent,
  type TtsVoiceRole,
} from '../../api/study'

interface Props {
  courseId: string
  node: PackNode
  active: boolean
  defaultMode?: LanguageChatMode
}

interface PracticeMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  translation_es?: string
  inline_correction_es?: string | null
  example_en?: string | null
  speaker_role?: LanguageSpeakerRole
  part_index?: number | null
  part_label?: string
}

interface SpeechRecognitionResultAlternativeLike {
  transcript: string
}

interface SpeechRecognitionResultLike {
  isFinal: boolean
  0: SpeechRecognitionResultAlternativeLike
  length: number
}

interface SpeechRecognitionEventLike {
  resultIndex: number
  results: ArrayLike<SpeechRecognitionResultLike>
}

interface SpeechRecognitionInstance {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onerror: (() => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionInstance

const SPEEDS = [0.8, 0.95, 1.0] as const
type ChatSpeed = (typeof SPEEDS)[number]

const EXAM_PARTS = [
  { index: 1, short: 'Parte 1/3', fallbackLabel: 'Preguntas personales' },
  { index: 2, short: 'Parte 2/3', fallbackLabel: 'Interacción en pareja' },
  { index: 3, short: 'Parte 3/3', fallbackLabel: 'Opinión y cierre' },
] as const

function getSpeechRecognitionCtor(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') return null
  const win = window as unknown as {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
  return win.SpeechRecognition ?? win.webkitSpeechRecognition ?? null
}

function isMediaRecorderAvailable(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof MediaRecorder !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    Boolean(navigator.mediaDevices?.getUserMedia)
  )
}

function pickSupportedAudioMimeType(): { mimeType: string; filename: string } {
  const candidates = [
    { mimeType: 'audio/webm;codecs=opus', filename: 'speech.webm' },
    { mimeType: 'audio/webm', filename: 'speech.webm' },
    { mimeType: 'audio/ogg;codecs=opus', filename: 'speech.ogg' },
    { mimeType: 'audio/ogg', filename: 'speech.ogg' },
  ]
  if (typeof MediaRecorder !== 'undefined' && typeof MediaRecorder.isTypeSupported === 'function') {
    for (const c of candidates) {
      if (MediaRecorder.isTypeSupported(c.mimeType)) return c
    }
  }
  return { mimeType: '', filename: 'speech.webm' }
}

function readStoredAccent(): TtsAccent {
  try {
    const stored = window.localStorage.getItem('brotal_tts_accent')
    if (stored === 'us' || stored === 'gb') return stored
  } catch {
    // Ignore storage errors
  }
  return 'us'
}

function stripBoldMarkers(text: string): string {
  return text.replace(/\*\*/g, '').trim()
}

function renderRecastText(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, idx) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong
          key={idx}
          className="rounded bg-teal-100/90 px-1 py-0.5 font-semibold text-teal-950 dark:bg-teal-900/70 dark:text-teal-100"
        >
          {part.slice(2, -2)}
        </strong>
      )
    }
    return <span key={idx}>{part}</span>
  })
}

export default function LanguageChatTab({
  courseId,
  node,
  active,
  defaultMode = 'missions',
}: Props) {
  const [mode, setMode] = useState<LanguageChatMode>(defaultMode)
  const [messages, setMessages] = useState<PracticeMessage[]>([])
  const [missions, setMissions] = useState<string[]>([])
  const [missionsCompleted, setMissionsCompleted] = useState<number[]>([])
  const [partIndex, setPartIndex] = useState<number | null>(defaultMode === 'exam_3parts' ? 1 : null)
  const [partLabel, setPartLabel] = useState<string>('')
  const [lexicalChips, setLexicalChips] = useState<string[]>([])
  const [sentenceStarter, setSentenceStarter] = useState<string | null>(null)
  const [sessionSummary, setSessionSummary] = useState<LanguageChatSessionSummary | null>(null)
  const [provider, setProvider] = useState<string | null>(null)

  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [initializing, setInitializing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [speed, setSpeed] = useState<ChatSpeed>(0.95)
  const [accent, setAccent] = useState<TtsAccent>(() => readStoredAccent())
  const [autoVoice, setAutoVoice] = useState(false)
  const [earOnly, setEarOnly] = useState(false)
  const [autoSendVoice, setAutoSendVoice] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)

  const [translatedIds, setTranslatedIds] = useState<Record<string, boolean>>({})
  const [revealedIds, setRevealedIds] = useState<Record<string, boolean>>({})

  const [loadingAudioKey, setLoadingAudioKey] = useState<string | null>(null)
  const [playingAudioKey, setPlayingAudioKey] = useState<string | null>(null)
  const [dictating, setDictating] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [recordingSeconds, setRecordingSeconds] = useState(0)
  const [micNotice, setMicNotice] = useState<string | null>(null)

  const msgCounterRef = useRef(0)
  const requestAbortRef = useRef<AbortController | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const blobUrlRef = useRef<string | null>(null)
  const ttsAbortRef = useRef<AbortController | null>(null)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const mediaChunksRef = useRef<Blob[]>([])
  const recordingTimerRef = useRef<number | null>(null)
  const sttAbortRef = useRef<AbortController | null>(null)
  const discardRecordingRef = useRef(false)
  const forceWebSpeechRef = useRef(false)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const modeRef = useRef<LanguageChatMode>(mode)
  modeRef.current = mode
  const autoVoiceRef = useRef(autoVoice)
  autoVoiceRef.current = autoVoice
  const autoSendVoiceRef = useRef(autoSendVoice)
  autoSendVoiceRef.current = autoSendVoice
  const speedRef = useRef(speed)
  speedRef.current = speed
  const accentRef = useRef(accent)
  accentRef.current = accent
  const latestInputRef = useRef(input)
  latestInputRef.current = input
  const busyRef = useRef(busy)
  busyRef.current = busy
  const messagesRef = useRef(messages)
  messagesRef.current = messages
  const sendTurnRef = useRef<(overrideText?: string) => Promise<void>>(async () => undefined)

  const mediaRecorderSupported = useMemo(() => isMediaRecorderAvailable(), [])
  const speechRecognitionSupported = useMemo(() => getSpeechRecognitionCtor() !== null, [])
  const micSupported = mediaRecorderSupported || speechRecognitionSupported

  const nextMsgId = () => {
    msgCounterRef.current += 1
    return `lchat-${node.id}-${msgCounterRef.current}`
  }

  const clearRecordingTimer = useCallback(() => {
    if (recordingTimerRef.current !== null) {
      window.clearInterval(recordingTimerRef.current)
      recordingTimerRef.current = null
    }
  }, [])

  const releaseMediaStream = useCallback(() => {
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop())
      mediaStreamRef.current = null
    }
  }, [])

  const stopAudio = useCallback(() => {
    if (ttsAbortRef.current) {
      ttsAbortRef.current.abort()
      ttsAbortRef.current = null
    }
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
      audioRef.current = null
    }
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current)
      blobUrlRef.current = null
    }
    setLoadingAudioKey(null)
    setPlayingAudioKey(null)
  }, [])

  const stopDictation = useCallback(
    (discardAudio = false) => {
      clearRecordingTimer()
      if (discardAudio) {
        discardRecordingRef.current = true
        if (sttAbortRef.current) {
          sttAbortRef.current.abort()
          sttAbortRef.current = null
        }
        setTranscribing(false)
      }
      if (mediaRecorderRef.current) {
        const rec = mediaRecorderRef.current
        mediaRecorderRef.current = null
        try {
          if (rec.state !== 'inactive') rec.stop()
        } catch {
          // Ignore if already stopped
        }
        if (discardAudio) {
          releaseMediaStream()
        }
      } else if (discardAudio) {
        releaseMediaStream()
      }
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop()
        } catch {
          // Ignore if already stopped
        }
        recognitionRef.current = null
      }
      setDictating(false)
      setRecordingSeconds(0)
    },
    [clearRecordingTimer, releaseMediaStream],
  )

  const playEnglishText = useCallback(
    async (
      audioKey: string,
      rawText: string,
      isAutoPlay = false,
      voiceRole: TtsVoiceRole = 'default',
    ) => {
      const clean = stripBoldMarkers(rawText)
      if (!clean) return
      if (!isAutoPlay && (playingAudioKey === audioKey || loadingAudioKey === audioKey)) {
        stopAudio()
        return
      }
      stopAudio()
      setLoadingAudioKey(audioKey)
      const ctrl = new AbortController()
      ttsAbortRef.current = ctrl

      try {
        const blob = await fetchPhraseTtsBlob(
          courseId || 'default',
          clean.slice(0, 1200),
          'en',
          accentRef.current,
          ctrl.signal,
          voiceRole,
        )
        if (ctrl.signal.aborted) return
        const url = URL.createObjectURL(blob)
        blobUrlRef.current = url
        const audio = new Audio(url)
        audio.playbackRate = speedRef.current
        audioRef.current = audio
        audio.onended = () => setPlayingAudioKey(null)
        audio.onerror = () => setPlayingAudioKey(null)
        setLoadingAudioKey(null)
        setPlayingAudioKey(audioKey)
        await audio.play()
      } catch {
        if (!ctrl.signal.aborted) {
          setLoadingAudioKey(null)
          setPlayingAudioKey(null)
        }
      }
    },
    [courseId, loadingAudioKey, playingAudioKey, stopAudio],
  )

  const startSession = useCallback(
    async (targetMode?: LanguageChatMode) => {
      const activeMode = targetMode ?? modeRef.current
      requestAbortRef.current?.abort()
      const ctrl = new AbortController()
      requestAbortRef.current = ctrl

      stopAudio()
      stopDictation(true)
      setError(null)
      setMicNotice(null)
      setInitializing(true)
      setBusy(true)
      setMessages([])
      setMissions([])
      setMissionsCompleted([])
      setPartIndex(activeMode === 'exam_3parts' ? 1 : null)
      setPartLabel('')
      setLexicalChips([])
      setSentenceStarter(null)
      setSessionSummary(null)
      setTranslatedIds({})
      setRevealedIds({})
      setHelpOpen(false)
      setInput('')

      try {
        const res = await sendLanguagePracticeChat(
          courseId,
          node.id,
          { start: true, turn_index: 0, mode: activeMode },
          ctrl.signal,
        )
        if (ctrl.signal.aborted) return
        const msgId = nextMsgId()
        const speakerRole: LanguageSpeakerRole | undefined =
          res.speaker_role ?? (activeMode === 'exam_3parts' ? 'teacher' : undefined)
        const resolvedPartIndex =
          typeof res.part_index === 'number'
            ? res.part_index
            : activeMode === 'exam_3parts'
              ? 1
              : null
        const resolvedPartLabel = res.part_label ?? ''

        const firstMsg: PracticeMessage = {
          id: msgId,
          role: 'assistant',
          content: res.reply_en,
          translation_es: res.translation_es,
          inline_correction_es: res.inline_correction_es ?? null,
          example_en: res.example_en ?? null,
          speaker_role: speakerRole,
          part_index: resolvedPartIndex,
          part_label: resolvedPartLabel,
        }
        setMessages([firstMsg])
        setMissions(Array.isArray(res.missions) ? res.missions : [])
        setMissionsCompleted(Array.isArray(res.missions_completed) ? res.missions_completed : [])
        setPartIndex(resolvedPartIndex)
        setPartLabel(resolvedPartLabel)
        setLexicalChips(Array.isArray(res.lexical_chips) ? res.lexical_chips : [])
        setSentenceStarter(res.sentence_starter ?? null)
        setSessionSummary(res.session_summary ?? null)
        setProvider(res.provider ?? null)

        if (autoVoiceRef.current && res.reply_en) {
          void playEnglishText(`msg:${msgId}`, res.reply_en, true, speakerRole ?? 'default')
        }
      } catch {
        if (ctrl.signal.aborted) return
        setError(
          'No se pudo iniciar la práctica conversacional. Verifica tu motor IA e intenta de nuevo.',
        )
      } finally {
        if (requestAbortRef.current === ctrl) {
          requestAbortRef.current = null
          setInitializing(false)
          setBusy(false)
        }
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [courseId, node.id, stopAudio, stopDictation],
  )

  // Auto-start Turn 0 the first time the user opens Práctica Chat for this node
  useEffect(() => {
    if (!active) {
      stopAudio()
      stopDictation(true)
      return
    }
    if (messages.length === 0 && !busy && !error && !requestAbortRef.current) {
      void startSession(modeRef.current)
    }
  }, [active, messages.length, busy, error, startSession, stopAudio, stopDictation])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      requestAbortRef.current?.abort()
      requestAbortRef.current = null
      stopAudio()
      stopDictation(true)
    }
  }, [stopAudio, stopDictation])

  useEffect(() => {
    if (active && messages.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [messages.length, sessionSummary, active])

  const handleSelectMode = (nextMode: LanguageChatMode) => {
    if (nextMode === mode) return
    setMode(nextMode)
    modeRef.current = nextMode
    void startSession(nextMode)
  }

  const handleSelectAccent = (nextAcc: TtsAccent) => {
    setAccent(nextAcc)
    try {
      window.localStorage.setItem('brotal_tts_accent', nextAcc)
    } catch {
      // Ignore storage errors
    }
  }

  const handleChangeSpeed = (nextSpeed: ChatSpeed) => {
    setSpeed(nextSpeed)
    if (audioRef.current) {
      audioRef.current.playbackRate = nextSpeed
    }
  }

  const userTurnCount = messages.filter((m) => m.role === 'user').length

  const buildHistory = (list: PracticeMessage[]): LanguageChatTurn[] =>
    list.map((m) => ({
      role: m.role,
      content: m.content,
    }))

  const sendTurn = async (overrideText?: string) => {
    const text = (overrideText ?? latestInputRef.current).trim()
    if (!text || busyRef.current) return
    stopDictation(true)
    setError(null)
    setMicNotice(null)

    const currentMessages = messagesRef.current
    const currentUserTurns = currentMessages.filter((m) => m.role === 'user').length
    const activeMode = modeRef.current

    const userMsg: PracticeMessage = {
      id: nextMsgId(),
      role: 'user',
      content: text,
    }
    const prevHistory = buildHistory(currentMessages)
    const nextTurnIndex = currentUserTurns + 1

    setMessages((prev) => [...prev, userMsg])
    setInput('')
    latestInputRef.current = ''
    setBusy(true)

    const ctrl = new AbortController()
    requestAbortRef.current = ctrl

    try {
      const res = await sendLanguagePracticeChat(
        courseId,
        node.id,
        {
          message: text,
          history: prevHistory,
          missions,
          turn_index: nextTurnIndex,
          mode: activeMode,
        },
        ctrl.signal,
      )
      if (ctrl.signal.aborted) return
      const assistantId = nextMsgId()
      const speakerRole: LanguageSpeakerRole | undefined =
        res.speaker_role ?? (activeMode === 'exam_3parts' ? 'teacher' : undefined)
      const resolvedPartIndex =
        typeof res.part_index === 'number' ? res.part_index : partIndex
      const resolvedPartLabel = res.part_label ?? partLabel

      const assistantMsg: PracticeMessage = {
        id: assistantId,
        role: 'assistant',
        content: res.reply_en,
        translation_es: res.translation_es,
        inline_correction_es: res.inline_correction_es ?? null,
        example_en: res.example_en ?? null,
        speaker_role: speakerRole,
        part_index: resolvedPartIndex,
        part_label: resolvedPartLabel,
      }
      setMessages((prev) => [...prev, assistantMsg])
      if (Array.isArray(res.missions) && res.missions.length > 0) {
        setMissions(res.missions)
      }
      if (Array.isArray(res.missions_completed)) {
        setMissionsCompleted(res.missions_completed)
      }
      if (typeof res.part_index === 'number') {
        setPartIndex(res.part_index)
      }
      if (typeof res.part_label === 'string' && res.part_label.trim()) {
        setPartLabel(res.part_label.trim())
      }
      setLexicalChips(Array.isArray(res.lexical_chips) ? res.lexical_chips : [])
      setSentenceStarter(res.sentence_starter ?? null)
      if (res.session_summary) {
        setSessionSummary(res.session_summary)
      }
      setProvider(res.provider ?? null)

      if (autoVoiceRef.current && res.reply_en) {
        void playEnglishText(`msg:${assistantId}`, res.reply_en, true, speakerRole ?? 'default')
      }
    } catch {
      if (ctrl.signal.aborted) return
      setError('No se pudo enviar tu mensaje. Intenta nuevamente.')
      setMessages((prev) => prev.filter((m) => m.id !== userMsg.id))
      setInput(text)
      latestInputRef.current = text
    } finally {
      if (requestAbortRef.current === ctrl) {
        requestAbortRef.current = null
        setBusy(false)
      }
    }
  }

  sendTurnRef.current = sendTurn

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    await sendTurn()
  }

  const handleFinish = async () => {
    if (busy || userTurnCount === 0) return
    stopDictation(true)
    setError(null)
    setBusy(true)

    const ctrl = new AbortController()
    requestAbortRef.current = ctrl
    const activeMode = modeRef.current

    try {
      const res = await sendLanguagePracticeChat(
        courseId,
        node.id,
        {
          history: buildHistory(messages),
          missions,
          turn_index: userTurnCount,
          finish: true,
          mode: activeMode,
        },
        ctrl.signal,
      )
      if (ctrl.signal.aborted) return
      if (res.reply_en && res.reply_en.trim()) {
        const closingId = nextMsgId()
        const speakerRole: LanguageSpeakerRole | undefined =
          res.speaker_role ?? (activeMode === 'exam_3parts' ? 'teacher' : undefined)
        setMessages((prev) => [
          ...prev,
          {
            id: closingId,
            role: 'assistant',
            content: res.reply_en,
            translation_es: res.translation_es,
            inline_correction_es: res.inline_correction_es ?? null,
            example_en: res.example_en ?? null,
            speaker_role: speakerRole,
            part_index: res.part_index ?? partIndex,
            part_label: res.part_label ?? partLabel,
          },
        ])
        if (autoVoiceRef.current) {
          void playEnglishText(`msg:${closingId}`, res.reply_en, true, speakerRole ?? 'default')
        }
      }
      if (Array.isArray(res.missions) && res.missions.length > 0) {
        setMissions(res.missions)
      }
      if (Array.isArray(res.missions_completed)) {
        setMissionsCompleted(res.missions_completed)
      }
      setSessionSummary(
        res.session_summary ?? {
          headline:
            activeMode === 'exam_3parts'
              ? 'Evaluación del Simulacro Oral (3 Partes)'
              : 'Resumen de tu práctica conversacional',
          items: [],
        },
      )
      setProvider(res.provider ?? null)
    } catch {
      if (ctrl.signal.aborted) return
      setError('No se pudo generar el resumen de la sesión. Intenta nuevamente.')
    } finally {
      if (requestAbortRef.current === ctrl) {
        requestAbortRef.current = null
        setBusy(false)
      }
    }
  }

  const handleRecognizedSpeech = (transcript: string) => {
    const clean = transcript.trim()
    if (!clean) return
    const prev = latestInputRef.current.trimEnd()
    const next = prev ? `${prev} ${clean}` : clean
    latestInputRef.current = next
    if (autoSendVoiceRef.current && !busyRef.current) {
      setInput('')
      latestInputRef.current = ''
      void sendTurnRef.current(next)
    } else {
      setInput(next)
      inputRef.current?.focus()
    }
  }

  const startWebSpeechMic = () => {
    const Ctor = getSpeechRecognitionCtor()
    if (!Ctor) {
      setMicNotice(
        'Tu navegador no soporta reconocimiento de voz; escribe tu respuesta en el campo de texto.',
      )
      return
    }
    try {
      const recognition = new Ctor()
      recognition.lang = accentRef.current === 'gb' ? 'en-GB' : 'en-US'
      recognition.continuous = false
      recognition.interimResults = false
      recognition.onresult = (event: SpeechRecognitionEventLike) => {
        const chunks: string[] = []
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const res = event.results[i]
          if (res.isFinal && res[0]?.transcript) {
            chunks.push(res[0].transcript.trim())
          }
        }
        const transcript = chunks.filter(Boolean).join(' ').trim()
        if (transcript) {
          handleRecognizedSpeech(transcript)
        }
      }
      recognition.onerror = () => {
        clearRecordingTimer()
        setDictating(false)
        setRecordingSeconds(0)
        recognitionRef.current = null
        setMicNotice(
          'No se pudo capturar audio del micrófono. Revisa los permisos o escribe tu mensaje.',
        )
      }
      recognition.onend = () => {
        clearRecordingTimer()
        setDictating(false)
        setRecordingSeconds(0)
        recognitionRef.current = null
      }
      recognitionRef.current = recognition
      setRecordingSeconds(0)
      setDictating(true)
      clearRecordingTimer()
      recordingTimerRef.current = window.setInterval(() => {
        setRecordingSeconds((s) => s + 1)
      }, 1000)
      recognition.start()
    } catch {
      clearRecordingTimer()
      setDictating(false)
      setRecordingSeconds(0)
      recognitionRef.current = null
      setMicNotice('No se pudo iniciar el micrófono en este navegador.')
    }
  }

  const toggleMic = async () => {
    if (busy || transcribing) return
    if (dictating) {
      stopDictation(false)
      return
    }
    setMicNotice(null)
    stopAudio()

    if (!mediaRecorderSupported || forceWebSpeechRef.current) {
      startWebSpeechMic()
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream
      const { mimeType, filename } = pickSupportedAudioMimeType()
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream)
      mediaChunksRef.current = []
      discardRecordingRef.current = false

      recorder.ondataavailable = (ev: BlobEvent) => {
        if (ev.data && ev.data.size > 0) {
          mediaChunksRef.current.push(ev.data)
        }
      }

      recorder.onerror = () => {
        clearRecordingTimer()
        releaseMediaStream()
        mediaRecorderRef.current = null
        setDictating(false)
        setRecordingSeconds(0)
        setMicNotice('Error al grabar audio del micrófono. Intenta nuevamente.')
      }

      recorder.onstop = () => {
        clearRecordingTimer()
        releaseMediaStream()
        mediaRecorderRef.current = null
        setDictating(false)
        setRecordingSeconds(0)

        if (discardRecordingRef.current) {
          mediaChunksRef.current = []
          return
        }

        const chunks = mediaChunksRef.current
        mediaChunksRef.current = []
        const blobType = recorder.mimeType || mimeType || 'audio/webm'
        const audioBlob = new Blob(chunks, { type: blobType })
        if (audioBlob.size === 0) {
          setMicNotice('No se capturó audio suficiente. Habla un poco más cerca del micrófono.')
          return
        }

        const ctrl = new AbortController()
        sttAbortRef.current = ctrl
        setTranscribing(true)

        const lastAssistant = [...messagesRef.current]
          .reverse()
          .find((m) => m.role === 'assistant')
        const promptHint = [node.title, lastAssistant ? stripBoldMarkers(lastAssistant.content) : '']
          .filter(Boolean)
          .join(' - ')
          .slice(0, 220)

        void transcribeStudyAudio(audioBlob, {
          language: 'en',
          promptHint,
          filename,
          signal: ctrl.signal,
        })
          .then((res) => {
            if (ctrl.signal.aborted) return
            const text = (res.text ?? '').trim()
            if (text) {
              handleRecognizedSpeech(text)
            } else {
              setMicNotice('No se detectó voz clara en el audio. Intenta de nuevo.')
            }
          })
          .catch((err: unknown) => {
            if (ctrl.signal.aborted) return
            if (err instanceof SttApiError && err.status === 503) {
              forceWebSpeechRef.current = true
              if (speechRecognitionSupported) {
                setMicNotice(
                  'STT en servidor no disponible (configura GROQ_API_KEY). Se activó el respaldo del navegador: pulsa el micrófono de nuevo.',
                )
              } else {
                setMicNotice(
                  'STT en servidor no disponible (falta GROQ_API_KEY) y este navegador no soporta dictado local.',
                )
              }
            } else {
              setMicNotice('No se pudo transcribir el audio. Intenta de nuevo o escribe tu mensaje.')
            }
          })
          .finally(() => {
            if (sttAbortRef.current === ctrl) {
              sttAbortRef.current = null
              setTranscribing(false)
            }
          })
      }

      mediaRecorderRef.current = recorder
      setRecordingSeconds(0)
      setDictating(true)
      clearRecordingTimer()
      recordingTimerRef.current = window.setInterval(() => {
        setRecordingSeconds((s) => s + 1)
      }, 1000)
      recorder.start()
    } catch {
      releaseMediaStream()
      clearRecordingTimer()
      setDictating(false)
      setRecordingSeconds(0)
      setMicNotice(
        'Permiso de micrófono denegado o dispositivo no disponible. Revisa los permisos o escribe tu respuesta.',
      )
    }
  }

  const insertHelperText = (snippet: string, replaceIfStarter = false) => {
    const clean = snippet.trim()
    if (!clean) return
    setInput((prev) => {
      if (replaceIfStarter && !prev.trim()) return `${clean} `
      const trimmed = prev.trimEnd()
      return trimmed ? `${trimmed} ${clean}` : clean
    })
    window.setTimeout(() => inputRef.current?.focus(), 20)
  }

  const isExamMode = mode === 'exam_3parts'
  const currentPart = partIndex ?? 1
  const completedSet = new Set(missionsCompleted)
  const completedCount = missions.filter((_, idx) => completedSet.has(idx)).length

  const summaryScore =
    sessionSummary && typeof sessionSummary.score_10 === 'number'
      ? sessionSummary.score_10
      : null
  const summaryPassed =
    sessionSummary?.passed !== undefined && sessionSummary?.passed !== null
      ? sessionSummary.passed
      : summaryScore !== null
        ? summaryScore >= PASS_SCORE
        : null

  return (
    <div className="flex min-w-0 max-w-full flex-col gap-3.5">
      {/* Selector de modo + barra compacta de controles */}
      <div className="flex flex-col gap-2 rounded-md border border-slate-200 bg-slate-50/80 px-3 py-2.5 text-xs dark:border-slate-700 dark:bg-slate-800/60">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div
            className="inline-flex flex-wrap items-center rounded-md border border-slate-300 bg-white p-0.5 dark:border-slate-600 dark:bg-slate-900"
            role="group"
            aria-label="Modo de práctica oral"
          >
            <button
              type="button"
              disabled={busy}
              aria-pressed={!isExamMode}
              onClick={() => handleSelectMode('missions')}
              className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-semibold transition disabled:opacity-60 ${
                !isExamMode
                  ? 'bg-teal-700 text-white dark:bg-teal-500 dark:text-slate-950'
                  : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
              }`}
            >
              <Sparkles size={12} />
              Práctica con Misiones
            </button>
            <button
              type="button"
              disabled={busy}
              aria-pressed={isExamMode}
              onClick={() => handleSelectMode('exam_3parts')}
              className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-semibold transition disabled:opacity-60 ${
                isExamMode
                  ? 'bg-indigo-700 text-white dark:bg-indigo-500 dark:text-slate-950'
                  : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
              }`}
            >
              <Award size={12} />
              Simulacro Oral (3 Partes)
            </button>
          </div>

          <div className="flex items-center gap-2">
            {provider && (
              <span className="hidden font-mono text-[10px] text-slate-500 sm:inline dark:text-slate-400">
                {provider}
              </span>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => void startSession(mode)}
              className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <RotateCcw size={12} />
              {isExamMode ? 'Reiniciar simulacro' : 'Reiniciar práctica'}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-slate-200/80 pt-2 dark:border-slate-700/80">
          {/* Velocidad */}
          <div
            className="inline-flex items-center rounded border border-slate-300 bg-white p-0.5 dark:border-slate-600 dark:bg-slate-900"
            role="group"
            aria-label="Velocidad de audio"
          >
            {SPEEDS.map((sp) => (
              <button
                key={sp}
                type="button"
                aria-pressed={speed === sp}
                onClick={() => handleChangeSpeed(sp)}
                className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold transition ${
                  speed === sp
                    ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                    : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                }`}
              >
                {sp}x
              </button>
            ))}
          </div>

          {/* Acento US / UK */}
          <div
            className="inline-flex items-center rounded border border-slate-300 bg-white p-0.5 dark:border-slate-600 dark:bg-slate-900"
            role="group"
            aria-label="Acento en inglés"
          >
            {(['us', 'gb'] as const).map((acc) => (
              <button
                key={acc}
                type="button"
                aria-pressed={accent === acc}
                onClick={() => handleSelectAccent(acc)}
                className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase transition ${
                  accent === acc
                    ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                    : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                }`}
              >
                {acc === 'us' ? 'US' : 'UK'}
              </button>
            ))}
          </div>

          {/* Toggle Auto-voz */}
          <button
            type="button"
            aria-pressed={autoVoice}
            onClick={() => setAutoVoice((v) => !v)}
            className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px] font-medium transition ${
              autoVoice
                ? 'border-teal-400 bg-teal-50 text-teal-900 dark:border-teal-600 dark:bg-teal-950/60 dark:text-teal-200'
                : 'border-slate-300 bg-white text-slate-600 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800'
            }`}
          >
            {autoVoice ? <Volume2 size={12} /> : <VolumeX size={12} />}
            Auto-voz: {autoVoice ? 'ON' : 'OFF'}
          </button>

          {/* Toggle Solo oído */}
          <button
            type="button"
            aria-pressed={earOnly}
            onClick={() => setEarOnly((v) => !v)}
            className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[11px] font-medium transition ${
              earOnly
                ? 'border-violet-400 bg-violet-50 text-violet-900 dark:border-violet-600 dark:bg-violet-950/60 dark:text-violet-200'
                : 'border-slate-300 bg-white text-slate-600 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800'
            }`}
          >
            <Ear size={12} />
            Solo oído: {earOnly ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>

      {/* Progreso visual Parte 1/3 · 2/3 · 3/3 en modo Simulacro Oral */}
      {isExamMode && (
        <div className="flex flex-col gap-2 rounded-md border border-indigo-200 bg-indigo-50/55 p-3 dark:border-indigo-800/70 dark:bg-indigo-950/25">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-indigo-900 dark:text-indigo-200">
              <Award size={13} className="text-indigo-600 dark:text-indigo-400" />
              Simulacro Oral · Parte {Math.min(Math.max(currentPart, 1), 3)}/3
            </span>
            {partLabel && (
              <span className="rounded-full border border-indigo-300 bg-white px-2.5 py-0.5 text-[11px] font-medium text-indigo-900 dark:border-indigo-700 dark:bg-slate-900 dark:text-indigo-200">
                {partLabel}
              </span>
            )}
          </div>
          <div className="grid grid-cols-3 gap-2">
            {EXAM_PARTS.map((step) => {
              const isDone = currentPart > step.index || Boolean(sessionSummary)
              const isCurrent = currentPart === step.index && !sessionSummary
              return (
                <div
                  key={step.index}
                  className={`flex items-center gap-1.5 rounded border px-2 py-1.5 text-[11px] font-medium transition ${
                    isCurrent
                      ? 'border-indigo-500 bg-indigo-600 text-white dark:border-indigo-400 dark:bg-indigo-500 dark:text-slate-950'
                      : isDone
                        ? 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-200'
                        : 'border-slate-200 bg-white text-slate-500 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-400'
                  }`}
                >
                  {isDone ? (
                    <CheckCircle2 size={12} className="shrink-0" />
                  ) : (
                    <Circle size={12} className="shrink-0" />
                  )}
                  <span className="truncate">{step.short}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Checklist visible de 3 misiones comunicativas (en modo misiones o si llegan misiones) */}
      {!isExamMode && missions.length > 0 && (
        <div className="rounded-md border border-teal-200 bg-teal-50/50 p-3 dark:border-teal-800/70 dark:bg-teal-950/25">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-teal-900 dark:text-teal-200">
              <Sparkles size={13} className="text-teal-600 dark:text-teal-400" />
              Misiones comunicativas
            </span>
            <span className="rounded-full border border-teal-300 bg-white px-2 py-0.5 font-mono text-[11px] font-semibold text-teal-900 dark:border-teal-700 dark:bg-slate-900 dark:text-teal-200">
              {completedCount}/{missions.length}
            </span>
          </div>
          <ul className="flex flex-col gap-1.5 text-xs">
            {missions.map((mission, idx) => {
              const done = completedSet.has(idx)
              return (
                <li
                  key={idx}
                  className={`flex items-start gap-2 rounded px-2 py-1 ${
                    done
                      ? 'bg-emerald-100/70 text-emerald-950 dark:bg-emerald-950/50 dark:text-emerald-200'
                      : 'text-slate-700 dark:text-slate-200'
                  }`}
                >
                  {done ? (
                    <CheckCircle2
                      size={14}
                      className="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400"
                    />
                  ) : (
                    <Circle
                      size={14}
                      className="mt-0.5 shrink-0 text-slate-400 dark:text-slate-500"
                    />
                  )}
                  <span className={done ? 'font-medium line-through decoration-emerald-500/60' : ''}>
                    {mission}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {/* Loader Turno 0 */}
      {initializing && (
        <div
          role="status"
          className="flex items-center gap-2.5 rounded-md border border-indigo-200 bg-indigo-50/70 px-3 py-4 text-xs text-indigo-950 dark:border-indigo-800/70 dark:bg-indigo-950/35 dark:text-indigo-200"
        >
          <Loader2 size={16} className="shrink-0 animate-spin text-indigo-600 dark:text-indigo-400" />
          <span>
            {isExamMode
              ? 'Preparando el Simulacro Oral de 3 Partes (Profesora + Compañero) para este taller...'
              : 'Preparando escenario de práctica y tus 3 misiones en inglés para este nodo...'}
          </span>
        </div>
      )}

      {/* Error + reintentar */}
      {error && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
          <span className="inline-flex items-center gap-1.5">
            <AlertCircle size={14} className="shrink-0" />
            {error}
          </span>
          {messages.length === 0 && (
            <button
              type="button"
              onClick={() => void startSession(mode)}
              className="rounded border border-rose-400 bg-white px-2.5 py-1 text-xs font-semibold text-rose-900 hover:bg-rose-100 dark:border-rose-700 dark:bg-slate-900 dark:text-rose-200 dark:hover:bg-rose-950"
            >
              Reintentar
            </button>
          )}
        </div>
      )}

      {/* Hilo de conversación */}
      {messages.length > 0 && (
        <div className="flex flex-col gap-3 rounded-md border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900/50">
          {messages.map((msg) => {
            if (msg.role === 'user') {
              return (
                <div key={msg.id} className="flex justify-end">
                  <div className="max-w-[88%] whitespace-pre-wrap break-words rounded-lg bg-slate-900 px-3.5 py-2.5 text-sm leading-relaxed text-white dark:bg-slate-100 dark:text-slate-900">
                    {msg.content}
                  </div>
                </div>
              )
            }

            const audioKey = `msg:${msg.id}`
            const isAudioLoading = loadingAudioKey === audioKey
            const isAudioPlaying = playingAudioKey === audioKey
            const isTranslated = Boolean(translatedIds[msg.id])
            const isBlurred = earOnly && !revealedIds[msg.id]
            const speakerRole = msg.speaker_role
            const voiceRole: TtsVoiceRole = speakerRole ?? 'default'

            const bubbleStyle =
              speakerRole === 'teacher'
                ? 'border-indigo-200 bg-indigo-50/50 dark:border-indigo-800/80 dark:bg-indigo-950/35'
                : speakerRole === 'partner'
                  ? 'border-teal-200 bg-teal-50/50 dark:border-teal-800/80 dark:bg-teal-950/35'
                  : 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/80'

            return (
              <div key={msg.id} className="flex flex-col items-start gap-1.5">
                <div
                  className={`max-w-[92%] rounded-lg border px-3.5 py-2.5 text-sm text-slate-900 dark:text-slate-100 ${bubbleStyle}`}
                >
                  {speakerRole && (
                    <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
                          speakerRole === 'teacher'
                            ? 'border-indigo-300 bg-indigo-100 text-indigo-900 dark:border-indigo-700 dark:bg-indigo-900/70 dark:text-indigo-200'
                            : 'border-teal-300 bg-teal-100 text-teal-900 dark:border-teal-700 dark:bg-teal-900/70 dark:text-teal-200'
                        }`}
                      >
                        {speakerRole === 'teacher' ? (
                          <GraduationCap size={12} />
                        ) : (
                          <UserRound size={12} />
                        )}
                        {speakerRole === 'teacher' ? 'Profesora' : 'Compañero'}
                      </span>
                      {typeof msg.part_index === 'number' && (
                        <span className="font-mono text-[10px] font-medium text-slate-500 dark:text-slate-400">
                          Parte {msg.part_index}/3
                          {msg.part_label ? ` · ${msg.part_label}` : ''}
                        </span>
                      )}
                    </div>
                  )}

                  <div
                    role={earOnly ? 'button' : undefined}
                    tabIndex={earOnly ? 0 : undefined}
                    title={
                      earOnly
                        ? isBlurred
                          ? 'Haz clic para revelar el texto en inglés'
                          : 'Haz clic para volver a ocultar'
                        : undefined
                    }
                    onClick={() => {
                      if (!earOnly) return
                      setRevealedIds((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))
                    }}
                    onKeyDown={(e) => {
                      if (!earOnly) return
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setRevealedIds((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))
                      }
                    }}
                    className={`break-words leading-relaxed transition ${
                      earOnly ? 'cursor-pointer' : ''
                    } ${isBlurred ? 'select-none blur-[6px]' : ''}`}
                  >
                    {renderRecastText(msg.content)}
                  </div>

                  <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-slate-200/80 pt-2 dark:border-slate-700/80">
                    <button
                      type="button"
                      onClick={() => void playEnglishText(audioKey, msg.content, false, voiceRole)}
                      className="inline-flex items-center gap-1 rounded border border-teal-300 bg-white px-2 py-0.5 text-[11px] font-medium text-teal-900 hover:bg-teal-50 dark:border-teal-700 dark:bg-slate-900 dark:text-teal-200 dark:hover:bg-teal-950/70"
                    >
                      {isAudioLoading ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : isAudioPlaying ? (
                        <Square size={10} />
                      ) : (
                        <Volume2 size={11} />
                      )}
                      {isAudioLoading ? 'Cargando...' : isAudioPlaying ? 'Detener' : 'Escuchar'}
                    </button>

                    {msg.translation_es && (
                      <button
                        type="button"
                        onClick={() =>
                          setTranslatedIds((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))
                        }
                        className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                      >
                        <Languages size={11} />
                        {isTranslated ? 'Ocultar traducción' : 'Traducir'}
                      </button>
                    )}

                    {earOnly && (
                      <button
                        type="button"
                        onClick={() =>
                          setRevealedIds((prev) => ({ ...prev, [msg.id]: !prev[msg.id] }))
                        }
                        className="inline-flex items-center gap-1 rounded border border-violet-300 bg-white px-2 py-0.5 text-[11px] font-medium text-violet-900 hover:bg-violet-50 dark:border-violet-700 dark:bg-slate-900 dark:text-violet-200 dark:hover:bg-violet-950/60"
                      >
                        {isBlurred ? <Eye size={11} /> : <EyeOff size={11} />}
                        {isBlurred ? 'Revelar texto' : 'Ocultar texto'}
                      </button>
                    )}
                  </div>

                  {isTranslated && msg.translation_es && (
                    <div className="mt-2 rounded border border-sky-200 bg-sky-50/70 px-2.5 py-1.5 text-xs text-sky-950 dark:border-sky-800/70 dark:bg-sky-950/40 dark:text-sky-200">
                      {msg.translation_es}
                    </div>
                  )}
                </div>

                {msg.inline_correction_es && (
                  <div className="max-w-[92%] rounded-md border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-950 dark:border-amber-800/70 dark:bg-amber-950/30 dark:text-amber-200">
                    <div className="flex items-start gap-1.5">
                      <Lightbulb
                        size={13}
                        className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400"
                      />
                      <div className="min-w-0 flex-1 break-words">
                        <span>{msg.inline_correction_es}</span>
                        {msg.example_en && (
                          <div className="mt-1 font-medium text-slate-900 dark:text-slate-100">
                            Ejemplo natural: <span className="italic">{msg.example_en}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )
          })}

          {busy && !initializing && (
            <div className="inline-flex w-fit items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
              <Loader2 size={13} className="animate-spin" />
              Escribiendo respuesta en inglés...
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      )}

      {/* Botón colapsable "Necesito ayuda" */}
      {messages.length > 0 && (lexicalChips.length > 0 || sentenceStarter) && (
        <div className="flex flex-col gap-2 rounded-md border border-slate-200 bg-slate-50/60 p-2.5 dark:border-slate-700 dark:bg-slate-800/40">
          <button
            type="button"
            aria-expanded={helpOpen}
            onClick={() => setHelpOpen((v) => !v)}
            className="inline-flex w-fit items-center gap-1.5 text-xs font-semibold text-slate-700 hover:text-slate-950 dark:text-slate-200 dark:hover:text-white"
          >
            <HelpCircle size={14} className="text-teal-600 dark:text-teal-400" />
            Necesito ayuda
            {helpOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>

          {helpOpen && (
            <div className="flex flex-col gap-2 pt-1">
              {lexicalChips.length > 0 && (
                <div className="flex flex-col gap-1">
                  <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">
                    Frases y vocabulario útil (clic para insertar):
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {lexicalChips.map((chip, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => insertHelperText(chip)}
                        className="rounded-full border border-teal-300 bg-white px-2.5 py-1 text-xs font-medium text-teal-900 hover:bg-teal-50 dark:border-teal-700 dark:bg-slate-900 dark:text-teal-200 dark:hover:bg-teal-950/70"
                      >
                        {chip}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {sentenceStarter && (
                <div className="flex flex-col gap-1">
                  <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">
                    Inicio de oración sugerido:
                  </span>
                  <button
                    type="button"
                    onClick={() => insertHelperText(sentenceStarter, true)}
                    className="w-fit rounded-md border border-indigo-300 bg-indigo-50/70 px-2.5 py-1.5 text-left text-xs font-medium text-indigo-950 hover:bg-indigo-100 dark:border-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-200 dark:hover:bg-indigo-900/60"
                  >
                    {sentenceStarter}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Dock híbrido Hablar + Teclado */}
      <form
        onSubmit={(e) => void handleSend(e)}
        className="flex flex-col gap-2 rounded-md border border-slate-200 bg-white p-2.5 dark:border-slate-700 dark:bg-slate-900/70"
      >
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void toggleMic()}
            disabled={busy || transcribing || !micSupported}
            title={
              micSupported
                ? transcribing
                  ? 'Transcribiendo audio...'
                  : dictating
                    ? 'Detener grabación y transcribir'
                    : 'Hablar en inglés por micrófono'
                : 'Dictado por voz no disponible en este navegador'
            }
            aria-label={
              transcribing
                ? 'Transcribiendo audio'
                : dictating
                  ? `Detener micrófono (${recordingSeconds}s)`
                  : 'Hablar en inglés'
            }
            className={`inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md border px-2.5 py-2 text-xs font-semibold transition disabled:opacity-40 ${
              dictating
                ? 'border-rose-400 bg-rose-50 text-rose-700 hover:bg-rose-100 dark:border-rose-700 dark:bg-rose-950/60 dark:text-rose-200'
                : transcribing
                  ? 'border-indigo-300 bg-indigo-50 text-indigo-800 dark:border-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-200'
                  : 'border-slate-300 bg-slate-50 text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700'
            }`}
          >
            {transcribing ? (
              <Loader2 size={15} className="animate-spin" />
            ) : dictating ? (
              <MicOff size={15} />
            ) : (
              <Mic size={15} />
            )}
            {transcribing
              ? 'Transcribiendo...'
              : dictating
                ? `Detener (${recordingSeconds}s)`
                : 'Hablar'}
          </button>

          <input
            ref={inputRef}
            type="text"
            value={input}
            disabled={busy || initializing || transcribing}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Responde en inglés (escribe o usa el micrófono)..."
            className="min-w-[160px] flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100"
          />

          <button
            type="submit"
            disabled={busy || initializing || transcribing || !input.trim()}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-40 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
          >
            <Send size={14} />
            Enviar
          </button>
        </div>

        {/* Toggle enviar automáticamente al terminar de hablar */}
        {micSupported && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              role="switch"
              aria-checked={autoSendVoice}
              onClick={() => setAutoSendVoice((v) => !v)}
              className={`inline-flex items-center gap-1.5 rounded border px-2 py-1 text-[11px] font-medium transition ${
                autoSendVoice
                  ? 'border-teal-400 bg-teal-50 text-teal-900 dark:border-teal-600 dark:bg-teal-950/60 dark:text-teal-200'
                  : 'border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300 dark:hover:bg-slate-800'
              }`}
            >
              <Zap size={12} />
              Enviar automáticamente al terminar de hablar: {autoSendVoice ? 'ON' : 'OFF'}
            </button>
          </div>
        )}

        {micNotice && (
          <p className="text-[11px] text-amber-700 dark:text-amber-300">{micNotice}</p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
          <span className="inline-flex items-center gap-1">
            <MessageSquare size={12} />
            Turnos enviados: {userTurnCount}
          </span>
          <button
            type="button"
            disabled={busy || transcribing || userTurnCount === 0}
            onClick={() => void handleFinish()}
            className="inline-flex items-center gap-1.5 rounded border border-indigo-300 bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-900 hover:bg-indigo-100 disabled:opacity-40 dark:border-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-200 dark:hover:bg-indigo-900/60"
          >
            <Flag size={12} />
            {isExamMode ? 'Terminar simulacro y calificar' : 'Terminar y ver resumen'}
          </button>
        </div>
      </form>

      {/* Tarjeta final de resumen (session_summary) */}
      {sessionSummary && (
        <div
          className={`flex flex-col gap-3 rounded-md border p-3.5 ${
            summaryPassed === false
              ? 'border-amber-300 bg-amber-50/50 dark:border-amber-800/80 dark:bg-amber-950/25'
              : 'border-emerald-300 bg-emerald-50/50 dark:border-emerald-800/80 dark:bg-emerald-950/25'
          }`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200/80 pb-2.5 dark:border-slate-700/70">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
              {summaryPassed === false ? (
                <Award size={16} className="shrink-0 text-amber-600 dark:text-amber-400" />
              ) : (
                <CheckCircle2 size={16} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
              )}
              <span>{sessionSummary.headline || 'Resumen de tu práctica'}</span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {summaryScore !== null && (
                <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-300 bg-white px-3 py-0.5 text-xs font-bold text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100">
                  <span>{summaryScore.toFixed(1)} / 10</span>
                  {summaryPassed !== null && (
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${
                        summaryPassed
                          ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/70 dark:text-emerald-200'
                          : 'bg-amber-100 text-amber-900 dark:bg-amber-900/70 dark:text-amber-200'
                      }`}
                    >
                      {summaryPassed ? 'Aprobado' : 'En progreso'}
                    </span>
                  )}
                </div>
              )}
              {sessionSummary.score_hint && (
                <span className="rounded-full border border-emerald-300 bg-white px-2.5 py-0.5 text-xs font-semibold text-emerald-900 dark:border-emerald-700 dark:bg-slate-900 dark:text-emerald-200">
                  {sessionSummary.score_hint}
                </span>
              )}
            </div>
          </div>

          {sessionSummary.items.length === 0 ? (
            <p className="text-xs text-slate-700 dark:text-slate-300">
              Excelente conversación: no se detectaron correcciones pendientes en tus respuestas.
            </p>
          ) : (
            <div className="flex flex-col gap-2.5">
              {sessionSummary.items.map((item, idx) => {
                const audioKey = `summary:${idx}`
                const isAudioLoading = loadingAudioKey === audioKey
                const isAudioPlaying = playingAudioKey === audioKey
                return (
                  <div
                    key={idx}
                    className="flex flex-col gap-2 rounded-md border border-slate-200 bg-white p-3 text-xs dark:border-slate-700 dark:bg-slate-900/80"
                  >
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <div className="flex flex-col gap-1">
                        <span className="text-[11px] font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-300">
                          Dijiste
                        </span>
                        <div className="rounded border border-rose-200 bg-rose-50/70 px-2.5 py-1.5 text-rose-950 dark:border-rose-800/70 dark:bg-rose-950/40 dark:text-rose-200">
                          {item.said}
                        </div>
                      </div>
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
                            Mejor en inglés
                          </span>
                          <button
                            type="button"
                            onClick={() => void playEnglishText(audioKey, item.better, false, 'teacher')}
                            className="inline-flex items-center gap-1 rounded border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-900 hover:bg-emerald-100 dark:border-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-200 dark:hover:bg-emerald-900/60"
                          >
                            {isAudioLoading ? (
                              <Loader2 size={11} className="animate-spin" />
                            ) : isAudioPlaying ? (
                              <Square size={10} />
                            ) : (
                              <Volume2 size={11} />
                            )}
                            {isAudioLoading ? 'Cargando...' : isAudioPlaying ? 'Detener' : 'Escuchar'}
                          </button>
                        </div>
                        <div className="rounded border border-emerald-200 bg-emerald-50/70 px-2.5 py-1.5 font-medium text-emerald-950 dark:border-emerald-800/70 dark:bg-emerald-950/40 dark:text-emerald-200">
                          {item.better}
                        </div>
                      </div>
                    </div>
                    <div className="break-words text-slate-700 dark:text-slate-300">
                      <strong className="font-semibold text-slate-900 dark:text-white">
                        Por qué:{' '}
                      </strong>
                      {item.why}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
