import { useEffect, useMemo, useRef, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { java } from '@codemirror/lang-java'
import { sql } from '@codemirror/lang-sql'
import { python } from '@codemirror/lang-python'
import { cpp } from '@codemirror/lang-cpp'
import { oneDark } from '@codemirror/theme-one-dark'
import {
  Bug,
  Code2,
  Eye,
  EyeOff,
  Languages,
  Lightbulb,
  Loader2,
  Mic,
  MicOff,
  PenLine,
  RotateCcw,
  Square,
  Terminal,
  Volume2,
} from 'lucide-react'
import {
  fetchPhraseTtsBlob,
  type ChallengeType,
  type CodeLanguage,
  type EvalPrompt,
  type TtsAccent,
} from '../../api/study'
import { useAppStore } from '../../store/useAppStore'

export type SupportLevel = 'guided' | 'transition' | 'exam'

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

function getSpeechRecognitionCtor(): SpeechRecognitionConstructor | null {
  if (typeof window === 'undefined') return null
  const win = window as unknown as {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
  return win.SpeechRecognition ?? win.webkitSpeechRecognition ?? null
}

interface Props {
  prompt: EvalPrompt
  index: number
  value: string
  onChange: (nextValue: string) => void
  courseId?: string
  engineType?: string
  supportLevel?: SupportLevel
  accent?: TtsAccent
  onAccentChange?: (accent: TtsAccent) => void
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

function buildGuidedHint(challengeType: ChallengeType, rubricPoints: string[]): string {
  const focus = rubricPoints[0] ? ` Enfoque evaluado: ${rubricPoints[0]}.` : ''
  if (challengeType === 'fill_blank') {
    return (
      'Fíjate si el sujeto es singular o plural, si el sustantivo es contable o incontable y si la oración es afirmativa, negativa o pregunta.' +
      focus
    )
  }
  if (challengeType === 'translate') {
    return (
      'Orden natural en inglés: Sujeto + Auxiliar/Verbo + Complemento (nunca omitas el pronombre sujeto y verifica tercera persona singular).' +
      focus
    )
  }
  return (
    'Estructura sugerida (3–4 oraciones): 1) Respuesta directa en inglés, 2) Detalle o frecuencia, 3) Ejemplo concreto.' +
    focus
  )
}

export default function CodeChallengeInput({
  prompt,
  index,
  value,
  onChange,
  courseId = 'default',
  engineType,
  supportLevel = 'guided',
  accent,
  onAccentChange,
}: Props) {
  const theme = useAppStore((s) => s.theme)
  const challengeType: ChallengeType = (prompt.challenge_type ?? 'concept') as ChallengeType
  const { question: cleanQuestion, starterCode } = useMemo(
    () => sanitizeCodePrompt(prompt.question, prompt.starter_code, prompt.language),
    [prompt.question, prompt.starter_code, prompt.language],
  )
  const langLabel = (prompt.language && prompt.language !== 'text' ? prompt.language : 'java').toUpperCase()

  const extensions = useMemo(() => getLanguageExtension(prompt.language), [prompt.language])
  const cmTheme = theme === 'dark' ? oneDark : 'light'

  const [localAccent, setLocalAccent] = useState<TtsAccent>('us')
  const activeAccent: TtsAccent = accent ?? localAccent
  const handleSelectAccent = (nextAccent: TtsAccent) => {
    setLocalAccent(nextAccent)
    onAccentChange?.(nextAccent)
  }

  const [loadingTts, setLoadingTts] = useState(false)
  const [playingTts, setPlayingTts] = useState(false)
  const [textRevealed, setTextRevealed] = useState(false)
  const [dictating, setDictating] = useState(false)

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const blobUrlRef = useRef<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const latestValueRef = useRef(value)
  latestValueRef.current = value

  const speechRecognitionSupported = useMemo(() => getSpeechRecognitionCtor() !== null, [])

  const playbackRate =
    supportLevel === 'guided' ? 0.8 : supportLevel === 'transition' ? 0.95 : 1.0

  const stopPhraseAudio = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
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
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
    setLoadingTts(false)
    setPlayingTts(false)
  }

  const stopDictation = () => {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {
        // Ignorar si ya estaba detenido
      }
      recognitionRef.current = null
    }
    setDictating(false)
  }

  useEffect(() => {
    setTextRevealed(false)
  }, [prompt.id, supportLevel])

  useEffect(() => {
    return () => {
      stopPhraseAudio()
      stopDictation()
    }
  }, [prompt.id])

  const playEnglishPhrase = async () => {
    if (playingTts || loadingTts) {
      stopPhraseAudio()
      return
    }
    const spokenText = cleanQuestion.replace(/^\[[^\]]+\]\s*/, '').trim() || cleanQuestion
    if (!spokenText) return

    setLoadingTts(true)
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const blob = await fetchPhraseTtsBlob(
        courseId || 'default',
        spokenText.slice(0, 1200),
        'en',
        activeAccent,
        controller.signal,
      )
      if (controller.signal.aborted) return
      const url = URL.createObjectURL(blob)
      blobUrlRef.current = url
      const audio = new Audio(url)
      audio.playbackRate = playbackRate
      audioRef.current = audio
      audio.onended = () => {
        setPlayingTts(false)
      }
      audio.onerror = () => {
        setPlayingTts(false)
      }
      setLoadingTts(false)
      setPlayingTts(true)
      await audio.play()
    } catch {
      if (controller.signal.aborted) return
      setLoadingTts(false)
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel()
        const utter = new SpeechSynthesisUtterance(spokenText)
        utter.lang = activeAccent === 'gb' ? 'en-GB' : 'en-US'
        utter.rate = playbackRate
        utter.onend = () => setPlayingTts(false)
        utter.onerror = () => setPlayingTts(false)
        setPlayingTts(true)
        window.speechSynthesis.speak(utter)
      } else {
        setPlayingTts(false)
      }
    }
  }

  const toggleDictation = () => {
    if (dictating) {
      stopDictation()
      return
    }
    const Ctor = getSpeechRecognitionCtor()
    if (!Ctor) return
    stopPhraseAudio()

    try {
      const recognition = new Ctor()
      recognition.lang = activeAccent === 'gb' ? 'en-GB' : 'en-US'
      recognition.continuous = true
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
          const prev = (latestValueRef.current ?? '').trimEnd()
          const next = prev ? `${prev} ${transcript}` : transcript
          latestValueRef.current = next
          onChange(next)
        }
      }
      recognition.onerror = () => {
        setDictating(false)
        recognitionRef.current = null
      }
      recognition.onend = () => {
        setDictating(false)
        recognitionRef.current = null
      }
      recognitionRef.current = recognition
      setDictating(true)
      recognition.start()
    } catch {
      setDictating(false)
      recognitionRef.current = null
    }
  }

  const isLanguageChallenge =
    challengeType === 'fill_blank' ||
    challengeType === 'translate' ||
    challengeType === 'speaking_prompt' ||
    (engineType === 'language_studio' && prompt.language === 'en')

  if (isLanguageChallenge) {
    const isSpeaking = challengeType === 'speaking_prompt'
    const isTranslate = challengeType === 'translate'
    const hideQuestionInitially = isSpeaking && supportLevel === 'exam' && !textRevealed

    const badgeConfig = isSpeaking
      ? {
          label: 'Speaking / Respuesta en inglés',
          icon: <Mic size={12} />,
          cls: 'border border-violet-300 bg-violet-50 text-violet-900 dark:border-violet-700/80 dark:bg-violet-950/50 dark:text-violet-200',
        }
      : isTranslate
        ? {
            label: 'Redactar en inglés',
            icon: <Languages size={12} />,
            cls: 'border border-teal-300 bg-teal-50 text-teal-900 dark:border-teal-700/80 dark:bg-teal-950/50 dark:text-teal-200',
          }
        : {
            label: 'Completar',
            icon: <PenLine size={12} />,
            cls: 'border border-sky-300 bg-sky-50 text-sky-900 dark:border-sky-700/80 dark:bg-sky-950/50 dark:text-sky-200',
          }

    const placeholderText = isSpeaking
      ? 'Write (or dictate) your answer in 3-4 complete sentences in English...'
      : isTranslate
        ? 'Write your complete sentence(s) in natural English...'
        : 'Type the missing words or the complete sentence in English...'

    return (
      <div className="flex min-w-0 flex-col gap-2.5 rounded-md border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900/60">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold ${badgeConfig.cls}`}>
              {badgeConfig.icon}
              {badgeConfig.label}
            </span>
            <span className="rounded border border-slate-300 bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300">
              EN · {playbackRate}x
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <div
              className="inline-flex rounded border border-slate-300 bg-slate-50 p-0.5 dark:border-slate-600 dark:bg-slate-800"
              role="group"
              aria-label="Acento en inglés"
            >
              {(['us', 'gb'] as const).map((acc) => (
                <button
                  key={acc}
                  type="button"
                  aria-pressed={activeAccent === acc}
                  onClick={() => handleSelectAccent(acc)}
                  className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase transition ${
                    activeAccent === acc
                      ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                      : 'text-slate-600 hover:bg-slate-200/70 dark:text-slate-300 dark:hover:bg-slate-700'
                  }`}
                >
                  {acc === 'us' ? 'US' : 'UK'}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={() => void playEnglishPhrase()}
              className="inline-flex items-center gap-1 rounded border border-teal-300 bg-teal-50 px-2.5 py-1 text-[11px] font-semibold text-teal-900 hover:bg-teal-100 dark:border-teal-700 dark:bg-teal-950/50 dark:text-teal-200 dark:hover:bg-teal-900/60"
            >
              {loadingTts ? (
                <Loader2 size={12} className="animate-spin" />
              ) : playingTts ? (
                <Square size={11} />
              ) : (
                <Volume2 size={12} />
              )}
              {loadingTts
                ? 'Generando...'
                : playingTts
                  ? 'Detener'
                  : hideQuestionInitially
                    ? 'Escuchar pregunta'
                    : supportLevel === 'guided'
                      ? 'Escuchar en inglés (0.8x)'
                      : 'Escuchar en inglés'}
            </button>

            {isSpeaking && supportLevel === 'exam' && (
              <button
                type="button"
                onClick={() => setTextRevealed((v) => !v)}
                className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                {textRevealed ? <EyeOff size={12} /> : <Eye size={12} />}
                {textRevealed ? 'Ocultar texto' : 'Mostrar texto'}
              </button>
            )}

            {isSpeaking && speechRecognitionSupported && (
              <button
                type="button"
                onClick={toggleDictation}
                className={`inline-flex items-center gap-1 rounded border px-2.5 py-1 text-[11px] font-semibold transition ${
                  dictating
                    ? 'border-rose-400 bg-rose-50 text-rose-800 hover:bg-rose-100 dark:border-rose-700 dark:bg-rose-950/60 dark:text-rose-200'
                    : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800'
                }`}
              >
                {dictating ? <MicOff size={12} /> : <Mic size={12} />}
                {dictating ? 'Detener dictado' : 'Dictar por micrófono'}
              </button>
            )}
          </div>
        </div>

        {hideQuestionInitially ? (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-dashed border-violet-300 bg-violet-50/50 px-3 py-2.5 text-xs text-violet-950 dark:border-violet-800 dark:bg-violet-950/30 dark:text-violet-200">
            <span>
              <strong>Pregunta {index + 1} (Modo Examen Real):</strong> escucha primero el audio en inglés a velocidad
              natural (1.0x) y responde sin leer el texto.
            </span>
          </div>
        ) : (
          <span className="break-words text-sm font-medium text-slate-900 dark:text-slate-100">
            {index + 1}. {cleanQuestion}
          </span>
        )}

        {supportLevel === 'guided' && (
          <div className="flex items-start gap-2 rounded border border-teal-200 bg-teal-50/60 px-2.5 py-1.5 text-xs text-teal-950 dark:border-teal-800/70 dark:bg-teal-950/30 dark:text-teal-200">
            <Lightbulb size={13} className="mt-0.5 shrink-0 text-teal-600 dark:text-teal-400" />
            <span className="break-words">{buildGuidedHint(challengeType, prompt.rubric_points)}</span>
          </div>
        )}

        <textarea
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value)}
          rows={isSpeaking ? 4 : 3}
          aria-label={`Respuesta pregunta ${index + 1}`}
          className="w-full rounded-md border border-slate-300 bg-white p-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 dark:border-slate-600 dark:bg-slate-900"
          placeholder={placeholderText}
        />
      </div>
    )
  }

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
