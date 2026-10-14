'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Check, Eye, EyeOff, FolderPlus, GripVertical, Loader2, Plus, Search, Trash2 } from 'lucide-react'
import { Button } from './ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './ui/dialog'
import {
  adminShowcaseAction, fetchTrendCategory, type ShowcaseCategory,
  type ShowcaseTrend, type ShowcaseSearchResult,
} from '@/lib/trend-catalog-api'

type EditableCategory = ShowcaseCategory & { id: number }

function reorder<T>(items: T[], origin: number, destination: number): T[] {
  if (origin < 0 || destination < 0 || origin >= items.length || destination >= items.length || origin === destination) {
    return items
  }
  const next = [...items]
  const moved = next.splice(origin, 1)[0]
  next.splice(destination, 0, moved)
  return next
}

export function TrendCategoryManager({ open, onOpenChange, categories, onRefresh }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  categories: ShowcaseCategory[]
  onRefresh: () => Promise<void>
}) {
  const realCategories = categories.filter((cat): cat is EditableCategory => typeof cat.id === 'number')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const selected = realCategories.find((cat) => cat.id === selectedId)
  const [title, setTitle] = useState('')
  const [emoji, setEmoji] = useState('✨')
  const [busy, setBusy] = useState(false)
  const [loadingItems, setLoadingItems] = useState(false)
  const [error, setError] = useState('')
  const [items, setItems] = useState<ShowcaseTrend[]>([])
  const [query, setQuery] = useState('')
  const [searchResult, setSearchResult] = useState<ShowcaseSearchResult | null>(null)
  const [searchLoading, setSearchLoading] = useState(false)
  const [targetById, setTargetById] = useState<Record<number, number>>({})
  const [badgeExpiry, setBadgeExpiry] = useState<Record<number, string>>({})
  const dragItem = useRef<number | null>(null)
  const itemRequest = useRef(0)
  const searchRequest = useRef(0)

  const loadItems = useCallback(async (categoryId: number) => {
    const request = ++itemRequest.current
    setLoadingItems(true)
    try {
      let page = 1
      let all: ShowcaseTrend[] = []
      let hasMore = false
      do {
        const result = await fetchTrendCategory(categoryId, page, 100)
        all = all.concat(result.items)
        hasMore = result.has_more
        if (all.length > 2000) throw new Error('Категория слишком большая для ручной сортировки. Обратитесь к администратору.')
        page += 1
      } while (hasMore)
      if (request === itemRequest.current) {
        setItems(all)
        setError('')
      }
    } catch (e) {
      if (request === itemRequest.current) setError(e instanceof Error ? e.message : 'Не удалось загрузить тренды папки')
    } finally {
      if (request === itemRequest.current) setLoadingItems(false)
    }
  }, [])

  useEffect(() => {
    if (!open || !selectedId) return
    void loadItems(selectedId)
    return () => { itemRequest.current += 1 }
  }, [open, selectedId, selected?.revision, loadItems])

  useEffect(() => {
    if (!open) return
    let active = true
    const timeout = window.setTimeout(async () => {
      const request = ++searchRequest.current
      setSearchLoading(true)
      try {
        const result = await adminShowcaseAction<ShowcaseSearchResult>({
          op: 'search_trends', query, page: 1, limit: 30,
        })
        if (active && request === searchRequest.current) setSearchResult(result)
      } catch (e) {
        if (active && request === searchRequest.current) setError(e instanceof Error ? e.message : 'Ошибка поиска')
      } finally {
        if (active && request === searchRequest.current) setSearchLoading(false)
      }
    }, 250)
    return () => { active = false; window.clearTimeout(timeout); searchRequest.current += 1 }
  }, [open, query])

  async function run(action: Parameters<typeof adminShowcaseAction>[0], onDone?: () => void) {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await adminShowcaseAction(action)
      await onRefresh()
      onDone?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить изменения')
      // A stale revision must never silently overwrite another admin's edits.
      await onRefresh().catch(() => undefined)
    } finally {
      setBusy(false)
    }
  }

  async function saveOrder(ordered: EditableCategory[]) {
    await run({ op: 'reorder', categories: ordered.map((cat) => ({
      id: cat.id, revision: cat.revision,
    })) })
  }

  async function saveItems(ordered: ShowcaseTrend[]) {
    if (!selected || loadingItems) return
    await run({
      op: 'set_items', category_id: selected.id, revision: selected.revision,
      trend_ids: ordered.map((item) => item.id),
    })
  }

  async function addItem(item: ShowcaseTrend) {
    if (!selected || items.some((old) => old.id === item.id)) return
    await saveItems([...items, item])
  }

  async function moveItem(item: ShowcaseTrend, targetId: number) {
    if (!selected || targetId === selected.id) return
    const dest = realCategories.find((cat) => cat.id === targetId)
    if (!dest) return
    await run({
      op: 'move_item',
      trend_id: item.id,
      source_id: selected.id, source_revision: selected.revision,
      target_id: dest.id, target_revision: dest.revision,
    } as Parameters<typeof adminShowcaseAction>[0])
  }

  function pointerTarget(e: React.PointerEvent<HTMLElement>) {
    const found = document.elementFromPoint(e.clientX, e.clientY)?.closest('[data-catalog-item]')
    const value = Number(found?.getAttribute('data-catalog-item') || 0)
    return Number.isSafeInteger(value) && value > 0 ? value : null
  }

  function dropItem(id: number, overId: number | null) {
    if (overId === null || id === overId) return
    const from = items.findIndex((item) => item.id === id)
    const to = items.findIndex((item) => item.id === overId)
    if (from !== -1 && to !== -1) void saveItems(reorder(items, from, to))
  }

  return (
    <Dialog open={open} onOpenChange={(value) => { if (!busy) onOpenChange(value) }}>
      <DialogContent className="max-h-[92dvh] max-w-2xl overflow-y-auto border-border/60 bg-background p-4">
        <DialogTitle className="pr-8 font-serif text-lg">Управление витриной</DialogTitle>
        <DialogDescription className="text-xs">
          Категории и порядок трендов меняются без переопубликования генераций. Существующие ссылки продолжают работать.
        </DialogDescription>
        {error ? <p role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{error}</p> : null}

        <section className="space-y-3 rounded-2xl border border-border/60 bg-secondary/20 p-3">
          <h3 className="text-sm font-semibold">Новая категория</h3>
          <div className="flex gap-2">
            <input
              value={emoji}
              aria-label="Эмодзи категории"
              maxLength={16}
              onChange={(e) => setEmoji(e.target.value)}
              className="w-14 rounded-lg border border-border bg-background px-2 text-center text-lg"
            />
            <input
              value={title}
              aria-label="Название категории"
              maxLength={60}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Видео на День рождения"
              className="h-11 min-w-0 flex-1 rounded-lg border border-border bg-background px-3 text-sm"
            />
            <Button disabled={busy || !title.trim()} type="button" onClick={() => void run({
              op: 'create', title, emoji,
            }, () => { setTitle(''); setEmoji('✨') })}>
              <FolderPlus className="h-4 w-4" /> Создать
            </Button>
          </div>

          <h3 className="text-sm font-semibold">Порядок категорий</h3>
          <div className="space-y-1.5">
            {realCategories.map((cat, index) => (
              <div key={cat.id} className={'flex items-center gap-2 rounded-xl border p-2 ' + (cat.id === selectedId ? 'border-gold/50 bg-gold/10' : 'border-border/50 bg-background/40')}>
                <button type="button" className="min-w-0 flex-1 truncate text-left text-sm" onClick={() => setSelectedId(cat.id)}>
                  {cat.emoji} {cat.title} <span className="text-xs text-muted-foreground">({cat.total})</span>
                  {!cat.is_visible ? <EyeOff className="ml-2 inline h-3 w-3" /> : null}
                </button>
                <button aria-label={'Категорию ' + cat.title + ' вверх'} disabled={busy || index === 0} onClick={() => void saveOrder(reorder(realCategories, index, index - 1))} className="rounded-lg border border-border/60 p-2 disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
                <button aria-label={'Категорию ' + cat.title + ' вниз'} disabled={busy || index === realCategories.length - 1} onClick={() => void saveOrder(reorder(realCategories, index, index + 1))} className="rounded-lg border border-border/60 p-2 disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
              </div>
            ))}
          </div>
        </section>

        {selected ? (
          <section className="space-y-3 rounded-2xl border border-gold/30 bg-secondary/15 p-3">
            <h3 className="font-semibold text-gold">{selected.emoji} {selected.title}</h3>
            <div className="grid grid-cols-[56px_minmax(0,1fr)] gap-2">
              <input
                aria-label="Изменить эмодзи"
                key={'emoji-' + selected.id + '-' + selected.revision}
                defaultValue={selected.emoji}
                maxLength={16}
                id="category-emoji-edit"
                className="h-11 rounded-lg border border-border bg-background p-2 text-center"
              />
              <input
                aria-label="Переименовать категорию"
                key={'title-' + selected.id + '-' + selected.revision}
                defaultValue={selected.title}
                maxLength={60}
                id="category-title-edit"
                className="h-11 rounded-lg border border-border bg-background px-3 text-sm"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" disabled={busy} onClick={() => {
                const name = document.getElementById('category-title-edit') as HTMLInputElement | null
                const icon = document.getElementById('category-emoji-edit') as HTMLInputElement | null
                void run({ op: 'update', category_id: selected.id, revision: selected.revision,
                  title: name?.value || selected.title, emoji: icon?.value || '' })
              }}><Check className="h-4 w-4" /> Сохранить</Button>
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => void run({
                op: 'update', category_id: selected.id, revision: selected.revision,
                is_visible: !selected.is_visible,
              })}>
                {selected.is_visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                {selected.is_visible ? 'Скрыть' : 'Показать'}
              </Button>
              <Button variant="destructive" size="sm" disabled={busy} onClick={() => {
                if (window.confirm('Удалить только категорию? Сами тренды и ссылки сохранятся.')) {
                  void run({ op: 'delete', category_id: selected.id, revision: selected.revision }, () => {
                    setSelectedId(null)
                    setItems([])
                  })
                }
              }}><Trash2 className="h-4 w-4" /> Удалить папку</Button>
            </div>

            <h3 className="text-sm font-semibold">Тренды внутри категории</h3>
            <p className="text-xs text-muted-foreground">Перетаскивайте за ручку или используйте стрелки для изменения порядка.</p>
            {loadingItems ? <Loader2 className="h-5 w-5 animate-spin" /> : null}
            <div className="space-y-2">
              {items.map((item, index) => (
                <div key={item.id} data-catalog-item={item.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-border/50 bg-background/50 p-2">
                  <span
                    role="button"
                    tabIndex={0}
                    aria-label={'Перетащить тренд ' + item.title}
                    className="cursor-grab touch-none rounded-md p-2 text-muted-foreground"
                    onPointerDown={(e) => {
                      dragItem.current = item.id
                      e.currentTarget.setPointerCapture(e.pointerId)
                    }}
                    onPointerUp={(e) => {
                      const origin = dragItem.current
                      dragItem.current = null
                      if (origin) dropItem(origin, pointerTarget(e))
                    }}
                    onPointerCancel={() => { dragItem.current = null }}
                    draggable
                    onDragStart={(e) => { dragItem.current = item.id; e.dataTransfer.effectAllowed = 'move' }}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => { e.preventDefault(); const origin = dragItem.current; dragItem.current = null; if (origin) dropItem(origin, item.id) }}
                  ><GripVertical className="h-5 w-5" /></span>
                  <span className="min-w-0 flex-1 truncate text-xs">{item.title}</span>
                  {item.badge === 'new' ? <span className="rounded bg-blue-500 px-1.5 text-[10px] text-white">Новинка</span> : null}
                  <button disabled={busy || index === 0} onClick={() => void saveItems(reorder(items, index, index - 1))} aria-label={'Тренд ' + item.title + ' вверх'} className="p-2 disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
                  <button disabled={busy || index === items.length - 1} onClick={() => void saveItems(reorder(items, index, index + 1))} aria-label={'Тренд ' + item.title + ' вниз'} className="p-2 disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
                  <div className="flex w-full flex-wrap items-center gap-2 pl-6 text-[11px]">
                    <button type="button" disabled={busy} className="rounded-md border border-gold/40 px-2 py-1 text-gold" onClick={() => void run({
                      op: 'set_badge', category_id: selected.id, trend_id: item.id,
                      revision: selected.revision, badge: 'new',
                      badge_until: badgeExpiry[item.id] ?? item.badge_until ?? null,
                    })}>
                      {item.badge === 'new' ? 'Сохранить новинку' : '+ Новинка'}
                    </button>
                    {item.badge === 'new' ? (
                      <button type="button" disabled={busy} className="rounded-md border border-border px-2 py-1" onClick={() => void run({
                        op: 'set_badge', category_id: selected.id, trend_id: item.id,
                        revision: selected.revision, badge: '',
                      })}>
                        Убрать новинку
                      </button>
                    ) : null}
                    <label className="inline-flex items-center gap-1 text-muted-foreground">
                      Новинка до
                      <input
                        type="date"
                        aria-label={'Новинка до для ' + item.title}
                        value={badgeExpiry[item.id] ?? item.badge_until ?? ''}
                        onChange={(e) => setBadgeExpiry((current) => ({ ...current, [item.id]: e.target.value }))}
                        className="h-8 rounded-md border border-border bg-background px-1 text-xs"
                      />
                    </label>
                    <button type="button" disabled={busy} className="rounded-md border border-border px-2 py-1" onClick={() => void saveItems(items.filter((row) => row.id !== item.id))}>
                      Убрать из папки
                    </button>
                    {realCategories.length > 1 ? (
                      <>
                        <select
                          aria-label={'Переместить ' + item.title + ' в категорию'}
                          className="h-8 min-w-0 max-w-[145px] rounded-md border border-border bg-background px-1"
                          value={targetById[item.id] || ''}
                          onChange={(e) => setTargetById((current) => ({ ...current, [item.id]: Number(e.target.value) }))}
                        >
                          <option value="">Переместить в…</option>
                          {realCategories.filter((cat) => cat.id !== selected.id).map((cat) => <option key={cat.id} value={cat.id}>{cat.emoji} {cat.title}</option>)}
                        </select>
                        {targetById[item.id] && targetById[item.id] !== selected.id ? (
                          <button disabled={busy} className="rounded-md border border-gold/50 px-2 py-1 text-gold" onClick={() => void moveItem(item, targetById[item.id])}>Перенести</button>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>

            <div className="space-y-2 border-t border-border/50 pt-3">
              <label className="flex items-center gap-2 text-sm font-semibold" htmlFor="showcase-trend-search"><Search className="h-4 w-4" /> Добавить опубликованный тренд</label>
              <input
                id="showcase-trend-search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Поиск по названию или ID"
                className="h-11 w-full rounded-lg border border-border bg-background px-3 text-sm"
              />
              {searchLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {(searchResult?.items || []).filter((trend) => !items.some((item) => item.id === trend.id)).map((trend) => (
                <div key={trend.id} className="flex items-center justify-between gap-2 rounded-lg border border-border/50 p-2 text-xs">
                  <span className="min-w-0 flex-1 truncate">{trend.title}</span>
                  <Button type="button" size="sm" variant="secondary" disabled={busy || loadingItems} onClick={() => void addItem(trend)}>
                    <Plus className="h-3.5 w-3.5" /> Добавить
                  </Button>
                </div>
              ))}
              {searchResult?.has_more ? <p className="text-xs text-muted-foreground">Уточните запрос, чтобы найти тренды за пределами первых 30 результатов.</p> : null}
            </div>
          </section>
        ) : (
          <div className="rounded-xl border border-dashed border-border p-5 text-center text-xs text-muted-foreground">
            Выберите категорию выше для настройки её трендов.
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
