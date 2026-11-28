import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Headphones,
  Info,
  Lightbulb,
  Loader2,
  RotateCcw,
  Square,
  Undo2,
  Volume2,
  X,
} from 'lucide-react'
import {
  fetchPhraseTtsBlob,
  type EvalPrompt,
  type TtsAccent,
} from '../../api/study'

export interface LanguageExerciseInputProps {
  prompt: EvalPrompt
  index: number
  value: string
  onChange: (nextValue: string) => void
  courseId?: string
  accent?: TtsAccent
  onAccentChange?: (accent: TtsAccent) => void
}

function asRecord(v: unknown): Record<string, unknown> {
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    return v as Record<string, unknown>
  }
  return {}
}

function asString(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

function asStringArray(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  return v
    .filter((x): x is string => typeof x === 'string')
    .map((x) => x.trim())
    .filter((x) => x.length > 0)
}

function asAccent(v: unknown): TtsAccent | undefined {
  if (v === 'us' || v === 'gb' || v === 'au') return v
  return undefined
}

function hashSeed(seed: string): number {
  let h = 2166136261
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

function deterministicShuffle<T>(items: T[], seedStr: string): T[] {
  const arr = [...items]
  let state = hashSeed(seedStr) || 1
  const nextRand = () => {
    state = (state + 0x6d2b79f5) | 0
    let t = Math.imul(state ^ (state >>> 15), 1 | state)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(nextRand() * (i + 1))
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr
}

function FallbackTextarea({
  index,
  value,
  onChange,
  placeholder,
  notice,
}: {
  index: number
  value: string
  onChange: (nextValue: string) => void
  placeholder: string
  notice?: string
}) {
  return (
    <div className="flex flex-col gap-2">
      {notice && (
        <div className="flex items-center gap-1.5 rounded border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
          <Info size={13} className="shrink-0" />
          <span>{notice}</span>
        </div>
      )}
      <textarea
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        aria-label={`Respuesta pregunta ${index + 1}`}
        className="w-full rounded-md border border-slate-300 bg-white p-2 text-sm text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
        placeholder={placeholder}
      />
    </div>
  )
}

function WordOrderExercise({
  prompt,
  index,
  value,
  onChange,
}: {
  prompt: EvalPrompt
  index: number
  value: string
  onChange: (nextValue: string) => void
}) {
  const data = asRecord(prompt.interaction_data)
  const tiles = useMemo(() => asStringArray(data.tiles), [data.tiles])
  const distractors = useMemo(() => asStringArray(data.distractors), [data.distractors])
  const hintEs = asString(data.hint_es)

  const shuffledTiles = useMemo(() => {
    const combined = [...tiles, ...distractors].map((word, tileIdx) => ({ tileIdx, word }))
    return deterministicShuffle(combined, `${prompt.id}:word_order`)
  }, [tiles, distractors, prompt.id])

  const tileByIdx = useMemo(() => {
    const map = new Map<number, string>()
    for (const t of shuffledTiles) {
      map.set(t.tileIdx, t.word)
    }
    return map
  }, [shuffledTiles])

  const [selectedIndices, setSelectedIndices] = useState<number[]>([])
  const lastEmittedRef = useRef<string | null>(null)

  useEffect(() => {
    if (lastEmittedRef.current !== null && value === lastEmittedRef.current) {
      return
    }
    const trimmed = (value ?? '').trim()
    if (!trimmed) {
      setSelectedIndices([])
      lastEmittedRef.current = ''
      return
    }
    // Reconstruct selected tile indices greedily from pre-populated value
    const words = trimmed.split(/\s+/)
    const used = new Set<number>()
    const next: number[] = []
    for (const w of words) {
      const match = shuffledTiles.find((t) => !used.has(t.tileIdx) && t.word === w)
      if (match) {
        used.add(match.tileIdx)
        next.push(match.tileIdx)
      }
    }
    setSelectedIndices(next)
    lastEmittedRef.current = next.map((idx) => tileByIdx.get(idx) ?? '').join(' ')
  }, [value, shuffledTiles, tileByIdx])

  if (tiles.length === 0) {
    return (
      <FallbackTextarea
        index={index}
        value={value}
        onChange={onChange}
        placeholder="Escribe la oración ordenada en inglés..."
        notice="Modo texto de respaldo: escribe la oración completa en el orden correcto."
      />
    )
  }

  const emitSelection = (next: number[]) => {
    setSelectedIndices(next)
    const serialized = next
      .map((idx) => tileByIdx.get(idx) ?? '')
      .filter(Boolean)
      .join(' ')
    lastEmittedRef.current = serialized
    onChange(serialized)
  }

  const handleAddTile = (tileIdx: number) => {
    if (selectedIndices.includes(tileIdx)) return
    emitSelection([...selectedIndices, tileIdx])
  }

  const handleRemoveTile = (tileIdx: number) => {
    emitSelection(selectedIndices.filter((i) => i !== tileIdx))
  }

  const handleUndo = () => {
    if (selectedIndices.length === 0) return
    emitSelection(selectedIndices.slice(0, -1))
  }

  const handleClear = () => {
    if (selectedIndices.length === 0) return
    emitSelection([])
  }

  const usedSet = new Set(selectedIndices)

  return (
    <div
      className="flex flex-col gap-2.5"
      onKeyDown={(e) => {
        const tag = (e.target as HTMLElement | null)?.tagName
        if (e.key === 'Backspace' && tag !== 'INPUT' && tag !== 'TEXTAREA') {
          if (selectedIndices.length > 0) {
            e.preventDefault()
            handleUndo()
          }
        }
      }}
    >
      {hintEs && (
        <div className="flex items-start gap-1.5 rounded border border-teal-200 bg-teal-50/70 px-2.5 py-1.5 text-xs text-teal-950 dark:border-teal-800/70 dark:bg-teal-950/30 dark:text-teal-200">
          <Lightbulb size={13} className="mt-0.5 shrink-0 text-teal-600 dark:text-teal-400" />
          <span className="break-words">{hintEs}</span>
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Tu oración armada
          </span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleUndo}
              disabled={selectedIndices.length === 0}
              className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <Undo2 size={11} />
              Deshacer
            </button>
            <button
              type="button"
              onClick={handleClear}
              disabled={selectedIndices.length === 0}
              className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              <RotateCcw size={11} />
              Limpiar
            </button>
          </div>
        </div>

        <div
          aria-label={`Zona de oración pregunta ${index + 1}`}
          tabIndex={0}
          className="flex min-h-[54px] flex-wrap items-center gap-1.5 rounded-md border-2 border-dashed border-slate-300 bg-slate-50/70 p-2.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 dark:border-slate-700 dark:bg-slate-950/50"
        >
          {selectedIndices.length === 0 ? (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              Haz clic en los bloques de abajo para construir la oración (usa Retroceso para deshacer).
            </span>
          ) : (
            selectedIndices.map((tileIdx) => {
              const word = tileByIdx.get(tileIdx) ?? ''
              return (
                <button
                  key={`placed-${tileIdx}`}
                  type="button"
                  onClick={() => handleRemoveTile(tileIdx)}
                  title="Quitar bloque"
                  className="inline-flex items-center gap-1 rounded-md border border-teal-400 bg-teal-50 px-2.5 py-1 text-sm font-medium text-teal-950 shadow-2xs transition hover:border-rose-400 hover:bg-rose-50 hover:text-rose-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 dark:border-teal-600 dark:bg-teal-950/70 dark:text-teal-100 dark:hover:border-rose-600 dark:hover:bg-rose-950/70 dark:hover:text-rose-200"
                >
                  <span>{word}</span>
                  <X size={12} className="opacity-70" />
                </button>
              )
            })
          )}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Bloques disponibles
          </span>
          {distractors.length > 0 && (
            <span className="text-[11px] text-amber-700 dark:text-amber-300">
              Nota: incluye 1-2 bloques distractores que sobran y no debes usar.
            </span>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5 rounded-md border border-slate-200 bg-white p-2.5 dark:border-slate-700 dark:bg-slate-900/50">
          {shuffledTiles.map((tile) => {
            const isUsed = usedSet.has(tile.tileIdx)
            return (
              <button
                key={`tray-${tile.tileIdx}`}
                type="button"
                disabled={isUsed}
                onClick={() => handleAddTile(tile.tileIdx)}
                className={`rounded-md border px-2.5 py-1 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                  isUsed
                    ? 'cursor-default border-dashed border-slate-200 bg-slate-100/60 text-slate-400 dark:border-slate-800 dark:bg-slate-800/30 dark:text-slate-600'
                    : 'border-slate-300 bg-slate-50 text-slate-900 hover:border-teal-400 hover:bg-teal-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:hover:border-teal-500 dark:hover:bg-teal-950/50'
                }`}
              >
                {tile.word}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function CategorizeExercise({
  prompt,
  index,
  value,
  onChange,
}: {
  prompt: EvalPrompt
  index: number
  value: string
  onChange: (nextValue: string) => void
}) {
  const data = asRecord(prompt.interaction_data)
  const categories = useMemo(() => asStringArray(data.categories), [data.categories])
  const rawItems = useMemo(() => asStringArray(data.items), [data.items])

  const shuffledItems = useMemo(
    () =>
      deterministicShuffle(
        rawItems.map((label, itemIdx) => ({ itemIdx, label })),
        `${prompt.id}:categorize`,
      ),
    [rawItems, prompt.id],
  )

  const [assignments, setAssignments] = useState<Record<number, string>>({})
  const [activeItemIdx, setActiveItemIdx] = useState<number | null>(null)
  const lastEmittedRef = useRef<string | null>(null)

  const serializeAssignments = (map: Record<number, string>): string => {
    const lines: string[] = []
    for (const cat of categories) {
      const itemsInCat = shuffledItems
        .filter((it) => map[it.itemIdx] === cat)
        .map((it) => it.label)
      if (itemsInCat.length > 0) {
        lines.push(`${cat}: ${itemsInCat.join(', ')}`)
      }
    }
    return lines.join('\n')
  }

  useEffect(() => {
    if (lastEmittedRef.current !== null && value === lastEmittedRef.current) {
      return
    }
    const trimmed = (value ?? '').trim()
    if (!trimmed) {
      setAssignments({})
      setActiveItemIdx(null)
      lastEmittedRef.current = ''
      return
    }
    const nextMap: Record<number, string> = {}
    const used = new Set<number>()
    for (const line of trimmed.split('\n')) {
      const colonIdx = line.indexOf(':')
      if (colonIdx === -1) continue
      const catName = line.slice(0, colonIdx).trim()
      if (!categories.includes(catName)) continue
      const parts = line
        .slice(colonIdx + 1)
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
      for (const part of parts) {
        const match = shuffledItems.find((it) => !used.has(it.itemIdx) && it.label === part)
        if (match) {
          used.add(match.itemIdx)
          nextMap[match.itemIdx] = catName
        }
      }
    }
    setAssignments(nextMap)
    setActiveItemIdx(null)
    lastEmittedRef.current = serializeAssignments(nextMap)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, categories, shuffledItems])

  if (categories.length === 0 || shuffledItems.length === 0) {
    return (
      <FallbackTextarea
        index={index}
        value={value}
        onChange={onChange}
        placeholder="Clasifica los elementos por categoría (Categoria: elemento1, elemento2)..."
        notice="Modo texto de respaldo: escribe cada categoría seguida de sus elementos."
      />
    )
  }

  const updateAssignments = (nextMap: Record<number, string>) => {
    setAssignments(nextMap)
    const serialized = serializeAssignments(nextMap)
    lastEmittedRef.current = serialized
    onChange(serialized)
  }

  const assignItem = (itemIdx: number, category: string) => {
    const nextMap = { ...assignments, [itemIdx]: category }
    setActiveItemIdx(null)
    updateAssignments(nextMap)
  }

  const unassignItem = (itemIdx: number) => {
    const nextMap = { ...assignments }
    delete nextMap[itemIdx]
    updateAssignments(nextMap)
  }

  const handleClear = () => {
    setActiveItemIdx(null)
    updateAssignments({})
  }

  const unassignedItems = shuffledItems.filter((it) => assignments[it.itemIdx] === undefined)
  const assignedCount = shuffledItems.length - unassignedItems.length

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-slate-600 dark:text-slate-300">
          {activeItemIdx !== null
            ? 'Ahora haz clic en una categoría para asignar el bloque seleccionado.'
            : 'Selecciona un bloque abajo y asígnalo a su categoría correspondiente.'}
        </span>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] text-slate-500 dark:text-slate-400">
            {assignedCount}/{shuffledItems.length}
          </span>
          <button
            type="button"
            onClick={handleClear}
            disabled={assignedCount === 0}
            className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-40 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <RotateCcw size={11} />
            Limpiar
          </button>
        </div>
      </div>

      <div
        className={`grid grid-cols-1 gap-2.5 ${
          categories.length >= 3 ? 'sm:grid-cols-2 lg:grid-cols-3' : 'sm:grid-cols-2'
        }`}
      >
        {categories.map((cat) => {
          const catItems = shuffledItems.filter((it) => assignments[it.itemIdx] === cat)
          const isTarget = activeItemIdx !== null
          return (
            <div
              key={cat}
              onClick={() => {
                if (activeItemIdx !== null) {
                  assignItem(activeItemIdx, cat)
                }
              }}
              className={`flex min-h-[96px] flex-col gap-2 rounded-md border p-2.5 transition ${
                isTarget
                  ? 'cursor-pointer border-teal-400 bg-teal-50/50 ring-1 ring-teal-400/50 hover:bg-teal-50 dark:border-teal-600 dark:bg-teal-950/35 dark:hover:bg-teal-950/60'
                  : 'border-slate-200 bg-slate-50/70 dark:border-slate-700 dark:bg-slate-950/40'
              }`}
            >
              <div className="flex items-center justify-between gap-2 border-b border-slate-200/80 pb-1.5 dark:border-slate-700/80">
                <span className="break-words text-xs font-semibold text-slate-900 dark:text-slate-100">
                  {cat}
                </span>
                {isTarget ? (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      if (activeItemIdx !== null) assignItem(activeItemIdx, cat)
                    }}
                    className="shrink-0 rounded bg-teal-600 px-1.5 py-0.5 text-[10px] font-semibold text-white hover:bg-teal-500 dark:bg-teal-500 dark:text-slate-950"
                  >
                    Asignar aquí
                  </button>
                ) : (
                  <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400">
                    {catItems.length}
                  </span>
                )}
              </div>

              <div className="flex flex-wrap gap-1.5">
                {catItems.length === 0 ? (
                  <span className="text-[11px] italic text-slate-400 dark:text-slate-500">
                    Sin elementos
                  </span>
                ) : (
                  catItems.map((it) => (
                    <button
                      key={`assigned-${it.itemIdx}`}
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        unassignItem(it.itemIdx)
                      }}
                      title="Quitar de esta categoría"
                      className="inline-flex items-center gap-1 rounded border border-indigo-300 bg-white px-2 py-0.5 text-xs font-medium text-slate-800 hover:border-rose-400 hover:bg-rose-50 hover:text-rose-900 dark:border-indigo-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-rose-600 dark:hover:bg-rose-950/60 dark:hover:text-rose-200"
                    >
                      <span>{it.label}</span>
                      <X size={11} className="opacity-70" />
                    </button>
                  ))
                )}
              </div>
            </div>
          )
        })}
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Bloques por asignar
        </span>
        <div className="flex flex-wrap gap-2 rounded-md border border-slate-200 bg-white p-2.5 dark:border-slate-700 dark:bg-slate-900/50">
          {unassignedItems.length === 0 ? (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-300">
              <CheckCircle2 size={14} />
              Todos los elementos fueron clasificados.
            </span>
          ) : (
            unassignedItems.map((it) => {
              const isSelected = activeItemIdx === it.itemIdx
              return (
                <div
                  key={`pool-${it.itemIdx}`}
                  className={`flex flex-wrap items-center gap-1 rounded-md border p-1 transition ${
                    isSelected
                      ? 'border-teal-500 bg-teal-50/70 ring-1 ring-teal-500 dark:border-teal-400 dark:bg-teal-950/50'
                      : 'border-slate-300 bg-slate-50 dark:border-slate-600 dark:bg-slate-800'
                  }`}
                >
                  <button
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => setActiveItemIdx(isSelected ? null : it.itemIdx)}
                    className="rounded px-2 py-0.5 text-xs font-medium text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 dark:text-slate-100"
                  >
                    {it.label}
                  </button>
                  {isSelected && (
                    <div className="flex flex-wrap items-center gap-1 border-l border-teal-300 pl-1.5 dark:border-teal-700">
                      {categories.map((cat) => (
                        <button
                          key={`quick-${it.itemIdx}-${cat}`}
                          type="button"
                          onClick={() => assignItem(it.itemIdx, cat)}
                          className="rounded bg-teal-700 px-1.5 py-0.5 text-[10px] font-semibold text-white hover:bg-teal-600 dark:bg-teal-500 dark:text-slate-950 dark:hover:bg-teal-400"
                        >
                          {cat}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}

function FindErrorExercise({
  prompt,
  index,
  value,
  onChange,
}: {
  prompt: EvalPrompt
  index: number
  value: string
  onChange: (nextValue: string) => void
}) {
  const data = asRecord(prompt.interaction_data)
  const sentence = asString(data.sentence)
  const rawTokens = useMemo(() => asStringArray(data.tokens), [data.tokens])
  const tokens = useMemo(() => {
    if (rawTokens.length > 0) return rawTokens
    if (sentence) return sentence.split(/\s+/).filter(Boolean)
    return []
  }, [rawTokens, sentence])
  const allowNoError = data.allow_no_error !== false

  const [mode, setMode] = useState<'none' | 'no_error' | 'token'>('none')
  const [selectedTokenIdx, setSelectedTokenIdx] = useState<number | null>(null)
  const [correction, setCorrection] = useState('')
  const correctionInputRef = useRef<HTMLInputElement | null>(null)
  const lastEmittedRef = useRef<string | null>(null)

  useEffect(() => {
    if (lastEmittedRef.current !== null && value === lastEmittedRef.current) {
      return
    }
    const trimmed = (value ?? '').trim()
    if (!trimmed) {
      setMode('none')
      setSelectedTokenIdx(null)
      setCorrection('')
      lastEmittedRef.current = ''
      return
    }
    if (trimmed === 'Sin error') {
      setMode('no_error')
      setSelectedTokenIdx(null)
      setCorrection('')
      lastEmittedRef.current = 'Sin error'
      return
    }
    const m = trimmed.match(/^Error:\s*(.+?)(?:\s*->\s*Correcci[oó]n:\s*(.*))?$/)
    if (m) {
      const tok = m[1].trim()
      const corr = (m[2] ?? '').trim()
      const foundIdx = tokens.findIndex((t) => t === tok)
      if (foundIdx !== -1) {
        setMode('token')
        setSelectedTokenIdx(foundIdx)
        setCorrection(corr)
        lastEmittedRef.current = trimmed
      }
    }
  }, [value, tokens])

  useEffect(() => {
    if (mode === 'token' && selectedTokenIdx !== null) {
      window.setTimeout(() => correctionInputRef.current?.focus(), 20)
    }
  }, [mode, selectedTokenIdx])

  if (tokens.length === 0) {
    return (
      <FallbackTextarea
        index={index}
        value={value}
        onChange={onChange}
        placeholder="Indica el error encontrado y su corrección (o escribe 'Sin error')..."
        notice="Modo texto de respaldo: identifica la palabra con error y escribe la forma correcta."
      />
    )
  }

  const emitValue = (nextVal: string) => {
    lastEmittedRef.current = nextVal
    onChange(nextVal)
  }

  const handleSelectToken = (tokIdx: number) => {
    const nextToken = tokens[tokIdx]
    setMode('token')
    setSelectedTokenIdx(tokIdx)
    const nextCorr = selectedTokenIdx === tokIdx ? correction : ''
    if (selectedTokenIdx !== tokIdx) setCorrection('')
    const c = nextCorr.trim()
    emitValue(c ? `Error: ${nextToken} -> Corrección: ${c}` : `Error: ${nextToken}`)
  }

  const handleSelectNoError = () => {
    setMode('no_error')
    setSelectedTokenIdx(null)
    setCorrection('')
    emitValue('Sin error')
  }

  const handleCorrectionChange = (nextCorr: string) => {
    setCorrection(nextCorr)
    if (selectedTokenIdx === null) return
    const tok = tokens[selectedTokenIdx]
    const trimmed = nextCorr.trim()
    emitValue(trimmed ? `Error: ${tok} -> Corrección: ${trimmed}` : `Error: ${tok}`)
  }

  const selectedToken = selectedTokenIdx !== null ? tokens[selectedTokenIdx] : null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Paso 1: Haz clic en el token con error{allowNoError ? ' o marca Sin error' : ''}
        </span>
        <div
          className="flex flex-wrap items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-700 dark:bg-slate-950/50"
          role="group"
          aria-label={`Tokens de la oración pregunta ${index + 1}`}
        >
          {tokens.map((tok, tokIdx) => {
            const isSelected = mode === 'token' && selectedTokenIdx === tokIdx
            return (
              <button
                key={`tok-${tokIdx}`}
                type="button"
                aria-pressed={isSelected}
                onClick={() => handleSelectToken(tokIdx)}
                className={`rounded-md border px-2.5 py-1.5 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500 ${
                  isSelected
                    ? 'border-rose-500 bg-rose-100 text-rose-950 ring-2 ring-rose-400/60 dark:border-rose-500 dark:bg-rose-950/70 dark:text-rose-100'
                    : 'border-slate-300 bg-white text-slate-900 hover:border-amber-400 hover:bg-amber-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-amber-500 dark:hover:bg-amber-950/40'
                }`}
              >
                {tok}
              </button>
            )
          })}

          {allowNoError && (
            <button
              type="button"
              aria-pressed={mode === 'no_error'}
              onClick={handleSelectNoError}
              className={`ml-auto inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
                mode === 'no_error'
                  ? 'border-emerald-500 bg-emerald-100 text-emerald-950 ring-2 ring-emerald-400/60 dark:border-emerald-500 dark:bg-emerald-950/70 dark:text-emerald-100'
                  : 'border-slate-300 bg-white text-slate-700 hover:border-emerald-400 hover:bg-emerald-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-emerald-600 dark:hover:bg-emerald-950/40'
              }`}
            >
              <CheckCircle2 size={13} />
              Sin error
            </button>
          )}
        </div>
      </div>

      {mode === 'token' && selectedToken !== null && (
        <div className="flex flex-col gap-1.5 rounded-md border border-amber-300/80 bg-amber-50/50 p-2.5 dark:border-amber-800/70 dark:bg-amber-950/25">
          <label
            htmlFor={`find-error-input-${prompt.id}`}
            className="flex flex-wrap items-center gap-1.5 text-xs font-semibold text-amber-950 dark:text-amber-200"
          >
            <AlertCircle size={13} className="shrink-0 text-amber-600 dark:text-amber-400" />
            <span>
              Paso 2: Escribe la corrección exacta para{' '}
              <code className="rounded bg-rose-100 px-1.5 py-0.5 font-mono text-rose-900 dark:bg-rose-950/80 dark:text-rose-200">
                {selectedToken}
              </code>
            </span>
          </label>
          <input
            id={`find-error-input-${prompt.id}`}
            ref={correctionInputRef}
            type="text"
            value={correction}
            onChange={(e) => handleCorrectionChange(e.target.value)}
            placeholder="Escribe la palabra o frase corregida en inglés..."
            className="w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
          />
          {!correction.trim() && (
            <span className="text-[11px] text-amber-800 dark:text-amber-300">
              Completa la corrección para registrar tu respuesta.
            </span>
          )}
        </div>
      )}
    </div>
  )
}

function DictationExercise({
  prompt,
  index,
  value,
  onChange,
  courseId = 'default',
  accent,
}: {
  prompt: EvalPrompt
  index: number
  value: string
  onChange: (nextValue: string) => void
  courseId?: string
  accent?: TtsAccent
}) {
  const data = asRecord(prompt.interaction_data)
  const audioText = asString(data.audio_text)
  const hintEs = asString(data.hint_es)
  const dataAccent = asAccent(data.accent)
  const effectiveAccent: TtsAccent = accent ?? dataAccent ?? 'us'

  const [loadingRate, setLoadingRate] = useState<number | null>(null)
  const [playingRate, setPlayingRate] = useState<number | null>(null)
  const [ttsError, setTtsError] = useState<string | null>(null)

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const blobUrlRef = useRef<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const stopAudio = () => {
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
    setLoadingRate(null)
    setPlayingRate(null)
  }

  useEffect(() => {
    return () => stopAudio()
  }, [prompt.id])

  const playAtRate = async (rate: 1.0 | 0.8) => {
    if (!audioText) return
    if (playingRate === rate || loadingRate === rate) {
      stopAudio()
      return
    }
    stopAudio()
    setTtsError(null)
    setLoadingRate(rate)

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      const blob = await fetchPhraseTtsBlob(
        courseId || 'default',
        audioText,
        'en',
        effectiveAccent,
        ctrl.signal,
      )
      if (ctrl.signal.aborted) return
      const url = URL.createObjectURL(blob)
      blobUrlRef.current = url
      const audio = new Audio(url)
      audio.playbackRate = rate
      audioRef.current = audio
      audio.onended = () => {
        setPlayingRate(null)
      }
      audio.onerror = () => {
        setPlayingRate(null)
        setTtsError('No se pudo reproducir el audio del dictado. Intenta nuevamente.')
      }
      setLoadingRate(null)
      setPlayingRate(rate)
      await audio.play()
    } catch {
      if (ctrl.signal.aborted) return
      setLoadingRate(null)
      setPlayingRate(null)
      setTtsError('No se pudo cargar el audio en este momento. Verifica tu conexión e intenta otra vez.')
    }
  }

  const isBusyOrPlaying = loadingRate !== null || playingRate !== null

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-indigo-200 bg-indigo-50/60 px-3 py-2.5 dark:border-indigo-800/70 dark:bg-indigo-950/35">
        <div className="flex items-center gap-2 text-xs text-indigo-950 dark:text-indigo-200">
          <Headphones size={15} className="shrink-0 text-indigo-600 dark:text-indigo-400" />
          <span>
            {audioText
              ? 'Escucha el audio a ciegas y escribe exactamente la oración en inglés.'
              : 'Audio no disponible para este reactivo; escribe tu respuesta según la consigna.'}
          </span>
        </div>

        {audioText && (
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => void playAtRate(1.0)}
              className="inline-flex items-center gap-1.5 rounded border border-indigo-300 bg-white px-2.5 py-1 text-xs font-semibold text-indigo-900 hover:bg-indigo-100 dark:border-indigo-700 dark:bg-slate-900 dark:text-indigo-200 dark:hover:bg-indigo-950/80"
            >
              {loadingRate === 1.0 ? (
                <Loader2 size={12} className="animate-spin" />
              ) : playingRate === 1.0 ? (
                <Square size={11} />
              ) : (
                <Volume2 size={12} />
              )}
              {loadingRate === 1.0
                ? 'Cargando...'
                : playingRate === 1.0
                  ? 'Detener (1.0x)'
                  : 'Escuchar (1.0x)'}
            </button>

            <button
              type="button"
              onClick={() => void playAtRate(0.8)}
              className="inline-flex items-center gap-1.5 rounded border border-teal-300 bg-white px-2.5 py-1 text-xs font-semibold text-teal-900 hover:bg-teal-100 dark:border-teal-700 dark:bg-slate-900 dark:text-teal-200 dark:hover:bg-teal-950/80"
            >
              {loadingRate === 0.8 ? (
                <Loader2 size={12} className="animate-spin" />
              ) : playingRate === 0.8 ? (
                <Square size={11} />
              ) : (
                <Volume2 size={12} />
              )}
              {loadingRate === 0.8
                ? 'Cargando...'
                : playingRate === 0.8
                  ? 'Detener (0.8x)'
                  : 'Lento (0.8x)'}
            </button>

            {isBusyOrPlaying && (
              <button
                type="button"
                onClick={stopAudio}
                className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                <Square size={11} />
                Detener
              </button>
            )}
          </div>
        )}
      </div>

      {ttsError && (
        <div className="flex items-center gap-1.5 rounded border border-amber-300 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <AlertCircle size={13} className="shrink-0" />
          <span>{ttsError}</span>
        </div>
      )}

      {hintEs && (
        <div className="flex items-start gap-1.5 rounded border border-teal-200 bg-teal-50/70 px-2.5 py-1.5 text-xs text-teal-950 dark:border-teal-800/70 dark:bg-teal-950/30 dark:text-teal-200">
          <Lightbulb size={13} className="mt-0.5 shrink-0 text-teal-600 dark:text-teal-400" />
          <span className="break-words">{hintEs}</span>
        </div>
      )}

      <textarea
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        aria-label={`Transcripción dictado pregunta ${index + 1}`}
        className="w-full rounded-md border border-slate-300 bg-white p-2.5 text-sm text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
        placeholder="Escribe exactamente lo que escuchaste en inglés..."
      />
    </div>
  )
}

export default function LanguageExerciseInput(props: LanguageExerciseInputProps) {
  const ct = props.prompt.challenge_type

  if (ct === 'word_order') {
    return (
      <WordOrderExercise
        prompt={props.prompt}
        index={props.index}
        value={props.value}
        onChange={props.onChange}
      />
    )
  }

  if (ct === 'categorize') {
    return (
      <CategorizeExercise
        prompt={props.prompt}
        index={props.index}
        value={props.value}
        onChange={props.onChange}
      />
    )
  }

  if (ct === 'find_error') {
    return (
      <FindErrorExercise
        prompt={props.prompt}
        index={props.index}
        value={props.value}
        onChange={props.onChange}
      />
    )
  }

  if (ct === 'dictation') {
    return (
      <DictationExercise
        prompt={props.prompt}
        index={props.index}
        value={props.value}
        onChange={props.onChange}
        courseId={props.courseId}
        accent={props.accent}
      />
    )
  }

  return (
    <FallbackTextarea
      index={props.index}
      value={props.value}
      onChange={props.onChange}
      placeholder="Escribe tu respuesta en inglés..."
    />
  )
}
