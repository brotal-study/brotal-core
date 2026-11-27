import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export interface StoryWord {
  globalWordIndex: number
  sentenceIndex: number
  wordInSentenceIndex: number
  text: string
  inlineCode?: boolean
  highlighted?: boolean
}

export interface StorySentence {
  globalIndex: number
  paragraphIndex: number
  text: string
  words: StoryWord[]
}

export type StoryBlock =
  | {
      type: 'paragraph'
      paragraphIndex: number
      sentences: StorySentence[]
    }
  | {
      type: 'code'
      language: string
      code: string
    }

function cleanSentenceDisplayText(sText: string): string {
  return sText
    .replace(/\*\*([^*\n]+)\*\*/g, '$1')
    .replace(/\*\*/g, '')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/`/g, '')
}

function tokenizeSentenceWords(
  sText: string,
  sIdx: number,
  startGlobalWordIndex: number,
  flatWords: StoryWord[],
): { words: StoryWord[]; nextGlobalWordIndex: number } {
  const words: StoryWord[] = []
  let globalWordIndex = startGlobalWordIndex
  let wordInSentenceIndex = 0

  // Separar segmentos con **negrita** y/o `codigo` sin mostrar marcadores crudos
  const boldSegments = sText.split(/(\*\*[^*\n]+\*\*)/g).filter(Boolean)
  for (const bSeg of boldSegments) {
    const isBoldOuter = bSeg.length >= 4 && bSeg.startsWith('**') && bSeg.endsWith('**')
    const innerBold = isBoldOuter ? bSeg.slice(2, -2) : bSeg.replace(/\*\*/g, '')

    const codeSegments = innerBold.split(/(`[^`\n]+`)/g).filter(Boolean)
    for (const cSeg of codeSegments) {
      const isCode = cSeg.length >= 2 && cSeg.startsWith('`') && cSeg.endsWith('`')
      const rawInner = isCode ? cSeg.slice(1, -1) : cSeg
      const hasInnerBold = rawInner.includes('**')
      const cleanSeg = rawInner.replace(/\*\*/g, '').replace(/`/g, '').trim()
      const tokens = cleanSeg.split(/\s+/).filter(Boolean)
      for (const wText of tokens) {
        const wItem: StoryWord = {
          globalWordIndex,
          sentenceIndex: sIdx,
          wordInSentenceIndex,
          text: wText,
          inlineCode: isCode,
          highlighted: isBoldOuter || hasInnerBold,
        }
        globalWordIndex += 1
        wordInSentenceIndex += 1
        flatWords.push(wItem)
        words.push(wItem)
      }
    }
  }

  return { words, nextGlobalWordIndex: globalWordIndex }
}

export function splitStoryParagraphSentences(rawText: string): {
  blocks: StoryBlock[]
  paragraphs: StorySentence[][]
  flat: StorySentence[]
  flatWords: StoryWord[]
} {
  const blocks: StoryBlock[] = []
  const paragraphs: StorySentence[][] = []
  const flat: StorySentence[] = []
  const flatWords: StoryWord[] = []
  let globalIndex = 0
  let globalWordIndex = 0
  let paragraphCounter = 0

  const addProseChunk = (proseChunk: string) => {
    const rawParagraphs = proseChunk
      .split(/\n{2,}/)
      .map((p) => p.trim())
      .filter(Boolean)

    for (const p of rawParagraphs) {
      const paragraphIndex = paragraphCounter++
      const parts =
        p
          .split(/(?<=[.!?])\s+/)
          .map((s) => s.trim())
          .filter(Boolean) ?? []
      const sentenceTexts = parts.length > 0 ? parts : [p]
      const pSentences: StorySentence[] = sentenceTexts.map((sText) => {
        const sIdx = globalIndex
        const { words, nextGlobalWordIndex } = tokenizeSentenceWords(
          sText,
          sIdx,
          globalWordIndex,
          flatWords,
        )
        globalWordIndex = nextGlobalWordIndex
        const item: StorySentence = {
          globalIndex: sIdx,
          paragraphIndex,
          text: cleanSentenceDisplayText(sText),
          words,
        }
        globalIndex += 1
        flat.push(item)
        return item
      })
      paragraphs.push(pSentences)
      blocks.push({
        type: 'paragraph',
        paragraphIndex,
        sentences: pSentences,
      })
    }
  }

  const fenceRegex = /```([a-zA-Z0-9_+-]*)[ \t]*\n?([\s\S]*?)```/g
  let lastIdx = 0
  let match: RegExpExecArray | null
  while ((match = fenceRegex.exec(rawText)) !== null) {
    if (match.index > lastIdx) {
      addProseChunk(rawText.slice(lastIdx, match.index))
    }
    const language = (match[1] || 'java').trim().toLowerCase()
    const code = (match[2] || '').replace(/^\n+|\n+$/g, '')
    if (code.trim().length > 0) {
      blocks.push({
        type: 'code',
        language,
        code,
      })
    }
    lastIdx = match.index + match[0].length
  }

  if (lastIdx < rawText.length) {
    const tail = rawText.slice(lastIdx).replace(/```[\s\S]*$/, '')
    addProseChunk(tail)
  }

  return { blocks, paragraphs, flat, flatWords }
}

// Fallback offline con window.speechSynthesis + seguimiento de oracion activa y salto por clic.
export function useSpeech(text: string) {
  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [state, setState] = useState<'idle' | 'playing' | 'paused'>('idle')
  const [rate, setRate] = useState(1)
  const [activeSentenceIndex, setActiveSentenceIndex] = useState<number | null>(null)
  const rateRef = useRef(rate)
  const run = useRef(0) // invalida cadenas de frases anteriores
  rateRef.current = rate

  const sentences = useMemo(
    () => splitStoryParagraphSentences(text).flat.map((s) => s.text),
    [text],
  )

  const stop = useCallback(() => {
    run.current++
    if (supported) window.speechSynthesis.cancel()
    setState('idle')
    setActiveSentenceIndex(null)
  }, [supported])

  const speakFrom = useCallback(
    (startIndex: number) => {
      if (!supported) return
      const synth = window.speechSynthesis
      synth.cancel()
      const id = ++run.current
      const list = sentences.length > 0 ? sentences : [text]
      const voice = synth.getVoices().find((v) => v.lang.toLowerCase().startsWith('es'))

      const speak = (i: number) => {
        if (id !== run.current) return
        if (i >= list.length) {
          setState('idle')
          setActiveSentenceIndex(null)
          return
        }
        setActiveSentenceIndex(i)
        const u = new SpeechSynthesisUtterance(list[i])
        u.lang = voice?.lang ?? 'es-ES'
        if (voice) u.voice = voice
        u.rate = rateRef.current
        u.onboundary = () => {
          if (id === run.current) setActiveSentenceIndex(i)
        }
        u.onend = () => speak(i + 1)
        u.onerror = () => {
          if (id === run.current) {
            setState('idle')
            setActiveSentenceIndex(null)
          }
        }
        synth.speak(u)
      }

      setState('playing')
      speak(Math.max(0, Math.min(startIndex, list.length - 1)))
    },
    [sentences, supported, text],
  )

  const play = useCallback(() => {
    if (!supported) return
    const synth = window.speechSynthesis
    if (state === 'paused') {
      synth.resume()
      setState('playing')
      return
    }
    speakFrom(0)
  }, [speakFrom, state, supported])

  const playFromSentence = useCallback(
    (index: number) => {
      speakFrom(index)
    },
    [speakFrom],
  )

  const pause = useCallback(() => {
    if (!supported) return
    window.speechSynthesis.pause()
    setState('paused')
  }, [supported])

  // Detener al cambiar de texto o desmontar.
  useEffect(() => stop, [text, stop])

  return {
    supported,
    state,
    rate,
    setRate,
    activeSentenceIndex,
    play,
    playFromSentence,
    pause,
    stop,
  }
}
