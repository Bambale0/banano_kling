'use client'

import { useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { referenceLibraryAction, uploadFile, type LibraryReference, type ReferenceCategory } from '@/lib/api'
import { normalizeMiniAppMediaUrl } from '@/lib/media-url'
import type { UploadedFile, UploadedFileType } from '@/lib/types'

export function PersonalReferenceLibrary({ kind: forcedKind, onSelect, disabled = false }: {
  kind?: UploadedFileType
  onSelect?: (file: UploadedFile) => void
  disabled?: boolean
}) {
  const [selectedKind, setSelectedKind] = useState<UploadedFileType>('image')
  const kind = forcedKind || selectedKind
  const [open, setOpen] = useState(false)
  const [managing, setManaging] = useState(!onSelect)
  const [categories, setCategories] = useState<ReferenceCategory[]>([])
  const [category, setCategory] = useState<string | null>(null)
  const [items, setItems] = useState<LibraryReference[]>([])
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [rename, setRename] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const lock = useRef(false)
  const generation = useRef(0)
  const [refresh, setRefresh] = useState(0)
  const selected = categories.find(item => item.id === category)

  useEffect(() => {
    if (!open) return
    const sequence = ++generation.current
    const controller = new AbortController()
    setLoading(true); setError(''); setItems([]); setNextOffset(null); setConfirmDelete(false)
    void (async () => {
      const catalog = await referenceLibraryAction('categories', { kind }, controller.signal)
      const page = category ? await referenceLibraryAction('items', { category_id: category, kind }, controller.signal) : null
      if (sequence !== generation.current) return
      setCategories(catalog.categories || [])
      setItems(page?.items || catalog.recent || [])
      setNextOffset(page?.next_offset ?? null)
      setRename(catalog.categories?.find(item => item.id === category)?.name || '')
    })().catch(cause => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Не удалось открыть референсы')
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => { controller.abort(); generation.current += 1 }
  }, [open, category, kind, refresh])

  const mutate = async (operation: () => Promise<void>, reload = true) => {
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try { await operation(); if (reload) setRefresh(value => value + 1) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Не удалось сохранить') }
    finally { lock.current = false; setBusy(false) }
  }

  return <>
    <Button type="button" variant="outline" disabled={disabled} onClick={() => setOpen(true)}>Мои референсы</Button>
    <Dialog open={open} onOpenChange={value => { if (!lock.current) setOpen(value) }}>
      <DialogContent className="max-h-[85dvh] max-w-xl overflow-y-auto">
        <DialogTitle>Мои референсы</DialogTitle>
        <DialogDescription>Сохраняйте варианты в свои категории и выбирайте их без повторной загрузки.</DialogDescription>
        <fieldset disabled={busy} className="space-y-4">
          {!forcedKind ? <select aria-label="Тип референса" value={kind} onChange={event => setSelectedKind(event.target.value as UploadedFileType)}
            className="rounded-lg border border-border bg-background p-2 text-sm">
            <option value="image">Фото</option><option value="video">Видео</option><option value="audio">Аудио</option>
          </select> : null}
          <div className="flex flex-wrap gap-2" role="group" aria-label="Категории референсов">
            <button type="button" aria-pressed={!category} onClick={() => setCategory(null)}
              className="rounded-full border border-border px-3 py-2 text-sm">Последние загрузки</button>
            {categories.map(item => <button key={item.id} type="button" aria-pressed={category === item.id}
              onClick={() => setCategory(item.id)} className={`min-w-0 max-w-full truncate rounded-full border px-3 py-2 text-sm ${category === item.id ? 'border-cyan text-cyan' : 'border-border'}`}>
              {item.name} ({item.count || 0})
            </button>)}
          </div>
          {onSelect ? <button type="button" className="text-sm text-cyan" onClick={() => setManaging(value => !value)}>
            {managing ? 'Вернуться к выбору' : categories.length ? 'Управлять категориями' : 'Создать категорию'}
          </button> : null}
          {managing ? <form className="flex gap-2" onSubmit={event => {
            event.preventDefault()
            void mutate(async () => {
              const response = await referenceLibraryAction('create_category', { name })
              setName(''); setCategory(response.category?.id || null)
            })
          }}>
            <Input aria-label="Название новой категории" placeholder="Например: Одежда" value={name} maxLength={80} onChange={event => setName(event.target.value)} />
            <Button type="submit" disabled={!name.trim()}>Создать</Button>
          </form> : null}
          {selected ? <div className="space-y-2 rounded-xl border border-border p-3">
            {managing ? <div className="flex gap-2">
              <Input aria-label="Название выбранной категории" value={rename} maxLength={80} onChange={event => setRename(event.target.value)} />
              <Button type="button" variant="outline" disabled={!rename.trim()} onClick={() => void mutate(async () => {
                await referenceLibraryAction('rename_category', { category_id: category, name: rename })
              })}>Переименовать</Button>
            </div> : null}
            <label className="inline-flex min-h-10 cursor-pointer items-center rounded-lg border border-cyan/50 px-3 text-sm text-cyan">
              Добавить файл в категорию
              <input type="file" accept={`${kind}/*`} disabled={busy} className="sr-only" onChange={event => {
                const file = event.target.files?.[0]; event.target.value = ''
                if (!file || !category) return
                void mutate(async () => { await uploadFile(`${kind}_reference`, file, category) })
              }} />
            </label>
            {managing ? <div className="flex flex-wrap items-center gap-2 text-xs">
              {confirmDelete ? <>
                <span className="min-w-0 break-all">Удалить категорию «{selected.name}»?</span>
                <Button type="button" variant="destructive" size="sm" onClick={() => void mutate(async () => {
                  await referenceLibraryAction('delete_category', { category_id: category }); setCategory(null)
                })}>Удалить категорию</Button>
                <button type="button" onClick={() => setConfirmDelete(false)}>Отмена</button>
              </> : <button type="button" className="text-muted-foreground" onClick={() => setConfirmDelete(true)}>Удалить категорию</button>}
            </div> : null}
          </div> : null}
          {loading ? <p role="status">Загрузка…</p> : null}
          {!loading && !items.length ? <p className="text-sm text-muted-foreground">Пока нет референсов{category ? ' в этой категории' : ''}.</p> : null}
          <div className="grid grid-cols-3 gap-2">
            {items.map(item => <div key={item.id} className="min-w-0 space-y-2 rounded-xl border border-border p-2">
              <button type="button" disabled={!onSelect || item.available === false} aria-label={`Выбрать ${item.title}`}
                className="block aspect-square w-full overflow-hidden rounded-lg bg-secondary"
                onClick={() => {
                  onSelect?.({ id: `saved_${item.id}`, saved_reference_id: item.id, name: item.title, type: item.kind, size: 0, url: item.url })
                  setOpen(false)
                }}>
                {item.kind === 'image' ? <img src={normalizeMiniAppMediaUrl(item.url)} alt={item.title} loading="lazy" className="h-full w-full object-contain" />
                  : <span className="break-all text-xs">{item.title}</span>}
              </button>
              <p className="truncate text-xs" title={item.title}>{item.title}</p>
              {item.available === false ? <p className="text-xs text-destructive">Файл недоступен</p> : null}
              {category && managing ? <>
                <Input key={`${item.id}:${item.title}`} aria-label={`Название референса ${item.title}`} defaultValue={item.title} maxLength={80}
                  onBlur={event => {
                    const title = event.target.value.trim()
                    if (title && title !== item.title) void mutate(async () => { await referenceLibraryAction('save_item', { category_id: category, reference_id: item.id, title }) })
                  }} className="h-8 text-xs" />
                <button type="button" className="text-xs text-muted-foreground" onClick={() => void mutate(async () => {
                  await referenceLibraryAction('remove_item', { category_id: category, reference_id: item.id })
                })}>Убрать из категории</button>
              </> : !category && managing ? <select aria-label={`Сохранить ${item.title} в категорию`} value="" className="w-full rounded border border-border bg-background text-xs"
                disabled={!categories.length || item.available === false} onChange={event => {
                  const id = event.target.value
                  if (id) void mutate(async () => { await referenceLibraryAction('save_item', { category_id: id, reference_id: item.id }) })
                }}>
                <option value="">Сохранить в…</option>
                {categories.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
              </select> : null}
            </div>)}
          </div>
          {nextOffset !== null ? <Button type="button" variant="outline" onClick={() => void mutate(async () => {
            const page = await referenceLibraryAction('items', { category_id: category, kind, offset: nextOffset })
            setItems(current => Array.from(new Map([...current, ...(page.items || [])].map(item => [item.id, item])).values()))
            setNextOffset(page.next_offset ?? null)
          }, false)}>Показать ещё</Button> : null}
        </fieldset>
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      </DialogContent>
    </Dialog>
  </>
}
