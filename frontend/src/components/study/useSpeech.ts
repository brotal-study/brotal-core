import { useCallback, useEffect, useRef, useState } from 'react'

// Fallback v0.1 con window.speechSynthesis. En v1.0 se reemplaza por audio edge-tts (POST .../tts).
export function useSpeech(text: string) {
  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window
  const [state, setState] = useState<'idle' | 'playing' | 'paused'>('idle')
  const [rate, setRate] = useState(1)
  const rateRef = useRef(rate)
  const run = useRef(0) // invalida cadenas de frases anteriores
  rateRef.current = rate

  const stop = useCallback(() => {
    run.current++
    if (supported) window.speechSynthesis.cancel()
    setState('idle')
  }, [supported])

  const play = useCallback(() => {
    if (!supported) return
    const synth = window.speechSynthesis
    if (state === 'paused') {
      synth.resume()
      setState('playing')
      return
    }
    synth.cancel()
    const id = ++run.current
    const sentences = text.match(/[^.!?]+[.!?]*/g)?.map((s) => s.trim()).filter(Boolean) ?? [text]
    const voice = synth.getVoices().find((v) => v.lang.toLowerCase().startsWith('es'))
    const speak = (i: number) => {
      if (id !== run.current) return
      if (i >= sentences.length) return setState('idle')
      const u = new SpeechSynthesisUtterance(sentences[i])
      u.lang = voice?.lang ?? 'es-ES'
      if (voice) u.voice = voice
      u.rate = rateRef.current
      u.onend = () => speak(i + 1)
      u.onerror = () => id === run.current && setState('idle')
      synth.speak(u)
    }
    setState('playing')
    speak(0)
  }, [supported, state, text])

  const pause = useCallback(() => {
    if (!supported) return
    window.speechSynthesis.pause()
    setState('paused')
  }, [supported])

  // Detener al cambiar de texto o desmontar.
  useEffect(() => stop, [text, stop])

  return { supported, state, rate, setRate, play, pause, stop }
}
