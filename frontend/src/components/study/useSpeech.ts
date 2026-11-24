import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export interface StorySentence {
  globalIndex: number
  paragraphIndex: number
  text: string
}

export function splitStoryParagraphSentences(rawText: string): {
  paragraphs: StorySentence[][]
  flat: StorySentence[]
} {
  const rawParagraphs = rawText
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean)

  const paragraphs: StorySentence[][] = []
  const flat: StorySentence[] = []
  let globalIndex = 0

  rawParagraphs.forEach((p, paragraphIndex) => {
    const parts =
      p
        .split(/(?<=[.!?])\s+/)
        .map((s) => s.trim())
        .filter(Boolean) ?? []
    const sentenceTexts = parts.length > 0 ? parts : [p]
    const pSentences: StorySentence[] = sentenceTexts.map((sText) => {
      const item: StorySentence = {
        globalIndex,
        paragraphIndex,
        text: sText,
      }
      globalIndex += 1
      flat.push(item)
      return item
    })
    paragraphs.push(pSentences)
  })

  return { paragraphs, flat }
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
