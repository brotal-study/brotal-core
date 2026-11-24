import { useEffect, useState } from 'react'

/** Reloj que avanza cada segundo solo mientras `active` (para cuentas regresivas de cooldown). */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    setNow(Date.now())
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [active])
  return now
}

export function formatRemaining(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000))
  if (s < 60) return `${s} s`
  const m = Math.ceil(s / 60)
  if (m < 60) return `${m} min`
  const h = Math.ceil(m / 60)
  if (h < 48) return `${h} h`
  return `${Math.ceil(h / 24)} días`
}

export const LEVEL_STYLE: Record<number, { bar: string; pill: string; accent: string }> = {
  0: {
    bar: 'bg-slate-400',
    pill: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
    accent: 'border-l-slate-400 dark:border-l-slate-600',
  },
  1: {
    bar: 'bg-amber-500',
    pill: 'bg-amber-100 text-amber-800 dark:bg-amber-900/60 dark:text-amber-200',
    accent: 'border-l-amber-500',
  },
  2: {
    bar: 'bg-sky-500',
    pill: 'bg-sky-100 text-sky-800 dark:bg-sky-900/60 dark:text-sky-200',
    accent: 'border-l-sky-500',
  },
  3: {
    bar: 'bg-emerald-500',
    pill: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/60 dark:text-emerald-200',
    accent: 'border-l-emerald-500',
  },
}
