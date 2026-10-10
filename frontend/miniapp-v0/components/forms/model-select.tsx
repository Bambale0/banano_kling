'use client'

import { useMemo, useState } from 'react'
import { cn } from '@/lib/utils'
import { Banana, Check, ChevronDown, Search } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

interface Model {
  id: string
  label: string
  description: string
  cost?: number
}

interface ModelSelectProps {
  models: Model[]
  value: string
  onChange: (value: string) => void
}

const NEW_MODEL_IDS = new Set(['wan_3_prime', 'seedance_2_5'])
const PAGE_SIZE = 8

const GROUP_LABELS: Record<string, string> = {
  all: 'Все',
  wan: 'Wan',
  seedance: 'Seedance',
  kling: 'Kling',
  grok: 'Grok',
  veo: 'Veo',
  gemini: 'Gemini',
  other: 'Другое',
}

type ModelGroup = 'wan' | 'seedance' | 'kling' | 'grok' | 'veo' | 'gemini' | 'other'

function modelGroup(model: Model): ModelGroup {
  const id = model.id.toLowerCase()
  if (id === 'wan_3_prime' || id.includes('wan')) return 'wan'
  if (id.startsWith('seedance')) return 'seedance'
  if (id.startsWith('veo3')) return 'veo'
  if (id.startsWith('grok')) return 'grok'
  if (id.includes('omni') || id.includes('gemini')) return 'gemini'
  if (id.startsWith('kling') || id.startsWith('v3') || id.startsWith('v26') || id === 'glow' || id.includes('motion_control') || id.includes('avatar')) return 'kling'
  return 'other'
}

function orderedGroupIds(models: Model[]) {
  const present = new Set(models.map(modelGroup))
  const order: Array<ModelGroup | 'all'> = ['all', 'wan', 'seedance', 'kling', 'grok', 'veo', 'gemini', 'other']
  return order.filter((id) => id === 'all' || present.has(id))
}

export function ModelSelect({ models, value, onChange }: ModelSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [activeGroup, setActiveGroup] = useState('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const selected = models.find(m => m.id === value)
  const selectedIsNew = selected ? NEW_MODEL_IDS.has(selected.id) : false
  const groups = useMemo(() => orderedGroupIds(models), [models])
  const orderedModels = useMemo(() => [...models].sort((left, right) => {
    const newDelta = Number(NEW_MODEL_IDS.has(right.id)) - Number(NEW_MODEL_IDS.has(left.id))
    if (newDelta) return newDelta
    return modelGroup(left).localeCompare(modelGroup(right)) || left.label.localeCompare(right.label)
  }), [models])
  const normalizedSearch = search.trim().toLowerCase()
  const filteredModels = useMemo(() => {
    const groupFiltered = activeGroup === 'all'
      ? orderedModels
      : orderedModels.filter((model) => modelGroup(model) === activeGroup)
    return normalizedSearch
      ? groupFiltered.filter((model) =>
        `${model.label} ${model.id} ${model.description}`.toLowerCase().includes(normalizedSearch)
      )
      : groupFiltered
  }, [activeGroup, normalizedSearch, orderedModels])
  const maxPage = Math.max(0, Math.ceil(filteredModels.length / PAGE_SIZE) - 1)
  const safePage = Math.min(page, maxPage)
  const pageModels = filteredModels.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE)

  const selectGroup = (group: string) => {
    setActiveGroup(group)
    setPage(0)
  }

  return (
    <div className="relative min-w-0">
      <button
        type="button"
        aria-expanded={isOpen}
        aria-haspopup="true"
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "w-full min-w-0 flex items-center justify-between gap-3 p-3 sm:p-4 rounded-xl",
          "bg-secondary/50 border border-border/50",
          "transition-all duration-200",
          "hover:bg-secondary hover:border-border",
          isOpen && "ring-2 ring-gold/30 border-gold/50"
        )}
      >
        <div className="min-w-0 flex-1 text-left">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-foreground">{selected?.label}</p>
            {selectedIsNew && (
              <span className="shrink-0 rounded-full border border-gold/60 bg-gold/25 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-gold shadow-[0_0_14px_rgba(251,191,36,0.2)]">
                NEW
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground line-clamp-1">{selected?.description}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="flex items-center gap-1 text-xs text-gold">
            <Banana className="w-3.5 h-3.5" />
            {selected?.cost ?? 'По расчёту'}
          </span>
          <ChevronDown className={cn(
            "w-4 h-4 text-muted-foreground transition-transform",
            isOpen && "rotate-180"
          )} />
        </div>
      </button>

      <AnimatePresence>
        {isOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-40"
              onClick={() => setIsOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, y: -8, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.95 }}
              transition={{ duration: 0.15 }}
              data-testid="model-select-menu"
              className={cn(
                "absolute z-50 mt-2 max-h-[68vh] w-full min-w-[min(88vw,22rem)] overflow-hidden rounded-xl py-2",
                "glass-strong border border-border/50 shadow-xl"
              )}
            >
              <div className="space-y-2 border-b border-border/40 px-2 pb-2">
                <div className="flex flex-wrap gap-1.5">
                  {groups.map((group) => (
                    <button
                      key={group}
                      type="button"
                      onClick={() => selectGroup(group)}
                      className={cn(
                        'rounded-lg border px-2.5 py-1.5 text-[11px] font-medium transition-colors',
                        activeGroup === group
                          ? 'border-gold/50 bg-gold/15 text-gold'
                          : 'border-border/50 bg-secondary/40 text-muted-foreground hover:bg-secondary hover:text-foreground'
                      )}
                    >
                      {GROUP_LABELS[group] || group}
                    </button>
                  ))}
                </div>
                <label className="flex items-center gap-2 rounded-lg border border-border/50 bg-secondary/40 px-2 py-1.5">
                  <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <input
                    aria-label="Поиск модели"
                    value={search}
                    onChange={(event) => {
                      setSearch(event.target.value)
                      setPage(0)
                    }}
                    placeholder="Поиск модели"
                    className="min-w-0 flex-1 bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
                  />
                </label>
              </div>
              <div className="max-h-[44vh] overflow-y-auto py-1">
                {pageModels.length ? pageModels.map((model) => {
                  const isNew = NEW_MODEL_IDS.has(model.id)
                  return (
                    <button
                      type="button"
                      key={model.id}
                      onClick={() => {
                        onChange(model.id)
                        setIsOpen(false)
                      }}
                      className={cn(
                        "w-full flex items-center gap-3 px-4 py-3",
                        "transition-colors",
                        "hover:bg-secondary/50",
                        model.id === value && "bg-gold/10",
                        isNew && "border-y border-gold/20 bg-gold/5"
                      )}
                    >
                      <div className="min-w-0 flex-1 text-left">
                        <div className="flex items-center gap-2">
                          <p className="truncate text-sm font-medium text-foreground">{model.label}</p>
                          {isNew && (
                            <span className="shrink-0 rounded-full border border-gold/60 bg-gold/25 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-gold shadow-[0_0_14px_rgba(251,191,36,0.2)]">
                              NEW
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground line-clamp-1">{model.description}</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <span className="flex items-center gap-1 text-xs text-gold">
                          <Banana className="w-3.5 h-3.5" />
                          {model.cost ?? 'По расчёту'}
                        </span>
                        {model.id === value && <Check className="w-4 h-4 text-gold" />}
                      </div>
                    </button>
                  )
                }) : (
                  <p className="px-4 py-6 text-center text-xs text-muted-foreground">Моделей не найдено</p>
                )}
              </div>
              {maxPage > 0 ? (
                <div className="flex items-center justify-between border-t border-border/40 px-3 pt-2 text-xs text-muted-foreground">
                  <button type="button" onClick={() => setPage(Math.max(0, safePage - 1))} className="rounded-lg px-2 py-1 hover:bg-secondary" disabled={safePage === 0}>Назад</button>
                  <span>{safePage + 1}/{maxPage + 1}</span>
                  <button type="button" onClick={() => setPage(Math.min(maxPage, safePage + 1))} className="rounded-lg px-2 py-1 hover:bg-secondary" disabled={safePage === maxPage}>Дальше</button>
                </div>
              ) : null}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
