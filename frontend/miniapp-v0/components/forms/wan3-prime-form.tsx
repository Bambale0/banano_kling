'use client'

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  fetchWan3PrimeOwnerRecipe, generateWan3Prime, importWan3PrimeReference,
  quoteWan3Prime, uploadWan3PrimeReference,
  type Wan3PrimeGenerateRequest, type Wan3PrimeGenerateResponse,
  type Wan3PrimeQuoteResponse, type Wan3PrimeRecipe, type Wan3PrimeScenario,
  type Wan3PrimeUploadKind,
} from '@/lib/wan3-prime-api'

const MODES: Array<[Wan3PrimeScenario, string]> = [
  ['text', 'По тексту'], ['first_frame', 'Первый кадр'], ['first_last', 'Первый и последний кадры'],
  ['reference', 'По референсам'], ['edit', 'Редактирование видео'], ['file', 'Из документа'], ['link', 'Из веб-страницы'],
]
const RATIOS = ['adaptive', '16:9', '4:3', '1:1', '3:4', '9:16'] as const
const ACCEPT = {
  image: '.jpg,.jpeg,.png,.bmp,.webp', video: '.mp4,.mov', audio: '.wav,.mp3',
  file: '.docx,.doc,.xlsx,.xls,.pptx,.ppt,.pdf,.txt,.key,.pages,.numbers,.md', link: '',
}
const CARD = 'min-w-0 space-y-3 rounded-2xl border border-border/50 bg-secondary/20 p-3 sm:p-4'
const SELECT = 'w-full min-w-0 rounded-lg border border-border bg-background p-2 text-sm'
function newId() { return crypto.randomUUID() }
function emptyRecipe(scenario: Wan3PrimeScenario = 'text'): Wan3PrimeRecipe {
  return { model: 'wan_3_prime', scenario, prompt: '', resolution: '1080P', aspect_ratio: 'adaptive',
    duration: 5, audio: true, nsfw_checker: false, seed: null, first_frame_url: null, last_frame_url: null,
    reference_image_urls: [], reference_video_urls: [], reference_audio_urls: [], reference_file_urls: [], reference_link_urls: [] }
}
function fileName(url: string) {
  try { return decodeURIComponent(new URL(url).pathname.split('/').pop() || 'Референс') } catch { return 'Референс' }
}
function recipeIssue(recipe: Wan3PrimeRecipe): string | null {
  const images = recipe.reference_image_urls || [], videos = recipe.reference_video_urls || [], audios = recipe.reference_audio_urls || []
  const files = recipe.reference_file_urls || [], links = recipe.reference_link_urls || []
  if (['text', 'edit'].includes(recipe.scenario) && !recipe.prompt.trim()) return 'Добавьте текст или инструкции изменения.'
  if (Array.from(recipe.prompt).length > 20000) return 'Максимальная длина инструкции — 20 000 символов.'
  if (recipe.duration !== -1 && (!Number.isInteger(recipe.duration) || recipe.duration < 2 || recipe.duration > 30)) return 'Выберите длительность 2–30 секунд или Auto.'
  if (recipe.seed != null && (!Number.isInteger(recipe.seed) || recipe.seed < 0 || recipe.seed > 2147483647)) return 'Seed должен быть целым числом от 0 до 2147483647.'
  if (images.length > 10 || videos.length > 5 || audios.length > 5 || files.length > 1 || links.length > 1) return 'Превышено число референсов Wan.'
  if ([...images, ...videos, ...audios, ...files, ...links].some(url => !url.trim())) return 'Добавьте исходное видео Video1; дополнительные референсы сохранены.'
  if (files.length && links.length) return 'Выберите документ или веб-страницу, не оба одновременно.'
  if (recipe.scenario === 'text' && (recipe.first_frame_url || recipe.last_frame_url || images.length || videos.length || audios.length || files.length || links.length)) return 'Текстовый режим не использует скрытые референсы.'
  if (['first_frame', 'first_last'].includes(recipe.scenario)) {
    if (!recipe.first_frame_url) return 'Загрузите первый кадр.'
    if (recipe.scenario === 'first_last' && !recipe.last_frame_url) return 'Загрузите последний кадр.'
    if (images.length || videos.length || audios.length || files.length || links.length) return 'Кадры не совмещаются с референсами.'
  }
  if (recipe.scenario === 'edit' && !videos[0]) return 'Загрузите исходное видео Video1.'
  if (recipe.scenario === 'reference' && !images.length && !videos.length && !audios.length && !files.length && !links.length) return 'Добавьте хотя бы один референс.'
  if (recipe.scenario === 'file' && !files.length) return 'Загрузите документ.'
  if (recipe.scenario === 'link' && !links.length) return 'Добавьте публичную веб-страницу.'
  return null
}

interface MediaFieldProps {
  title: string; label: string; prefix: string; kind: Wan3PrimeUploadKind | 'link'; values: string[]
  limit: number; offset?: number; disabled?: boolean; hint?: string
  onChange: (values: string[]) => void; onBusy: (delta: number) => void; onError: (message: string) => void
}
function MediaField({ title, label, prefix, kind, values, limit, offset = 1, disabled, hint, onChange, onBusy, onError }: MediaFieldProps) {
  const [external, setExternal] = useState('')
  const [names, setNames] = useState<Record<string, string>>({})
  const lock = useRef(false)
  const upload = async (files: File[]) => {
    if (!files.length || lock.current) return
    if (files.length + values.length > limit) { onError(`Можно добавить максимум ${limit}. Выбранные файлы не загружены.`); return }
    lock.current = true; onBusy(1)
    let next = [...values]
    try {
      for (const file of files) {
        const stored = await uploadWan3PrimeReference(kind as Wan3PrimeUploadKind, file)
        next = [...next, stored.url]
        setNames(old => ({ ...old, [stored.url]: file.name }))
        onChange(next)
      }
    } catch (error) { onError(error instanceof Error ? error.message : 'Не удалось загрузить файл.') }
    finally { lock.current = false; onBusy(-1) }
  }
  const importUrl = async () => {
    if (lock.current || !external.trim()) return
    if (values.length >= limit) { onError(`Сначала удалите один из ${limit} референсов.`); return }
    lock.current = true; onBusy(1)
    try {
      const stored = await importWan3PrimeReference(kind, external.trim())
      onChange([...values, stored.url]); setExternal('')
      setNames(old => ({ ...old, [stored.url]: stored.filename || (kind === 'link' ? new URL(stored.url).hostname : fileName(stored.url)) }))
    } catch (error) { onError(error instanceof Error ? error.message : 'Не удалось проверить ссылку.') }
    finally { lock.current = false; onBusy(-1) }
  }
  return <section className={CARD} aria-label={title}>
    <div className="flex items-center justify-between gap-2"><h4 className="text-sm font-semibold">{title}</h4><span className="text-xs text-muted-foreground">{values.length}/{limit}</span></div>
    {hint ? <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p> : null}
    {values.map((url, index) => <div key={`${index}-${url}`} className="flex min-w-0 items-center gap-2 rounded-lg border border-border/40 p-2 text-xs">
      <span className="shrink-0 font-medium">{prefix}{offset + index}</span>
      <span className="min-w-0 flex-1 break-all">{names[url] || fileName(url)}</span>
      <button type="button" disabled={disabled} aria-label={`Удалить ${prefix}${offset + index}`} onClick={() => onChange(values.filter((_, i) => i !== index))} className="shrink-0 rounded px-2 py-1 hover:bg-secondary disabled:opacity-40">×</button>
    </div>)}
    {kind !== 'link' ? <label className="block space-y-1 text-xs">
      <span>{label}</span><input type="file" aria-label={label} accept={ACCEPT[kind]} multiple={limit > 1} disabled={disabled || values.length >= limit}
        className="block w-full min-w-0 text-xs file:mr-2 file:rounded-lg file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-foreground"
        onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ''; void upload(files) }} />
    </label> : null}
    <details className="text-xs"><summary className="cursor-pointer py-1 text-muted-foreground">{kind === 'link' ? 'Добавить адрес страницы' : 'Импортировать по ссылке'}</summary>
      <div className="mt-2 flex min-w-0 gap-2"><Input aria-label={`Ссылка: ${title}`} value={external} onChange={e => setExternal(e.target.value)} placeholder="https://…" disabled={disabled} className="min-w-0 text-xs" />
        <Button type="button" variant="outline" size="sm" disabled={disabled || !external.trim()} onClick={() => { void importUrl() }}>Добавить</Button></div>
    </details>
  </section>
}

interface Wan3PrimeFormProps {
  credits: number; isAdmin?: boolean; modelSelector?: ReactNode; initialRecipe?: Wan3PrimeRecipe | null
  ownerTaskId?: string | null; publicationSourceId?: number | null; disabledReason?: string
  onQueued?: (result: Wan3PrimeGenerateResponse) => void | Promise<void>
}
export function Wan3PrimeForm({ credits, isAdmin = false, modelSelector, initialRecipe, ownerTaskId, publicationSourceId, disabledReason: externalDisabledReason, onQueued }: Wan3PrimeFormProps) {
  const disabledReason = externalDisabledReason || (publicationSourceId ? 'Повтор публикации Wan требует проверки прав на исходные материалы.' : '')
  const [recipe, setRecipe] = useState<Wan3PrimeRecipe>(() => initialRecipe ? { ...emptyRecipe(), ...initialRecipe } : emptyRecipe())
  const drafts = useRef<Partial<Record<Wan3PrimeScenario, Wan3PrimeRecipe>>>({})
  const [requestId, setRequestId] = useState(newId)
  const [pending, setPending] = useState(0)
  const [quoting, setQuoting] = useState(false)
  const [sending, setSending] = useState(false)
  const [attempted, setAttempted] = useState(false)
  const [quoteState, setQuoteState] = useState<{ snapshot: string; quote: Wan3PrimeQuoteResponse } | null>(null)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Wan3PrimeGenerateResponse | null>(null)
  const frozenRequest = useRef<Wan3PrimeGenerateRequest | null>(null)
  const submitLock = useRef(false)
  const snapshot = JSON.stringify(recipe)
  const currentSnapshot = useRef(snapshot); currentSnapshot.current = snapshot
  const approved = quoteState?.snapshot === snapshot ? quoteState.quote : null
  const issue = recipeIssue(recipe)
  const working = pending > 0 || quoting || sending
  const locked = working || attempted || Boolean(disabledReason)
  const isFrames = recipe.scenario === 'first_frame' || recipe.scenario === 'first_last'
  const isReferences = ['reference', 'edit', 'file', 'link'].includes(recipe.scenario)
  const additionalKind = recipe.reference_file_urls?.length ? 'file' : recipe.reference_link_urls?.length ? 'link' : 'none'
  const [extraSource, setExtraSource] = useState<'none' | 'file' | 'link'>(additionalKind)
  const onBusy = (delta: number) => setPending(n => Math.max(0, n + delta))
  const patch = (value: Partial<Wan3PrimeRecipe>) => { setRecipe(old => ({ ...old, ...value })); setError('') }

  useEffect(() => {
    if (!ownerTaskId) return
    const abort = new AbortController()
    setPending(n => n + 1)
    void fetchWan3PrimeOwnerRecipe(ownerTaskId, abort.signal).then(value => {
      if (!abort.signal.aborted) { setRecipe({ ...emptyRecipe(), ...value.recipe }); setQuoteState(null); setAttempted(false); setResult(null); frozenRequest.current = null; setRequestId(newId()) }
    }).catch(error => { if (!abort.signal.aborted) setError(error instanceof Error ? error.message : 'Не удалось восстановить собственную задачу.') })
      .finally(() => { if (!abort.signal.aborted) setPending(n => Math.max(0, n - 1)) })
    return () => abort.abort()
  }, [ownerTaskId])
  useEffect(() => {
    if (initialRecipe && !attempted) setRecipe({ ...emptyRecipe(), ...initialRecipe })
  }, [initialRecipe]) // A new owner recipe is an explicit user selection, not a provider prompt.

  const selectMode = (mode: Wan3PrimeScenario) => {
    if (locked) return
    drafts.current[recipe.scenario] = recipe
    const next = drafts.current[mode] || { ...emptyRecipe(mode), prompt: recipe.prompt, resolution: recipe.resolution,
      aspect_ratio: recipe.aspect_ratio, duration: recipe.duration, seed: recipe.seed, audio: recipe.audio, nsfw_checker: recipe.nsfw_checker }
    setRecipe(next); setQuoteState(null); setError('')
    setExtraSource(next.reference_file_urls?.length ? 'file' : next.reference_link_urls?.length ? 'link' : 'none')
  }
  const calculate = async () => {
    if (working || attempted || issue || disabledReason) return
    const key = snapshot; setQuoting(true); setError('')
    try {
      const value = await quoteWan3Prime({ recipe, client_request_id: requestId })
      if (!value.quote_hash || !Number.isFinite(value.reserve_cost) || value.reserve_cost < 0) throw new Error('Сервер не подтвердил стоимость. Повторите расчёт.')
      if (currentSnapshot.current === key) setQuoteState({ snapshot: key, quote: value })
    } catch (error) { if (currentSnapshot.current === key) setError(error instanceof Error ? error.message : 'Не удалось рассчитать стоимость.') }
    finally { setQuoting(false) }
  }
  const launch = async () => {
    if (submitLock.current || working || disabledReason || (!frozenRequest.current && (!approved || issue))) return
    if (!frozenRequest.current) frozenRequest.current = { recipe, client_request_id: requestId, idempotency_key: requestId, quote_hash: approved!.quote_hash }
    submitLock.current = true; setSending(true); setAttempted(true); setError('')
    try {
      const value = await generateWan3Prime(frozenRequest.current)
      setResult(value)
      try { await onQueued?.(value) } catch { /* Accepted work stays accepted if history refresh fails. */ }
    } catch (error) {
      const code = error && typeof error === 'object' && 'code' in error ? String(error.code) : ''
      if (['stale_quote', 'validation_error', 'missing_rate', 'insufficient_credits'].includes(code)) {
        setAttempted(false); frozenRequest.current = null; setQuoteState(null)
        setError(error instanceof Error ? error.message : 'Обновите расчёт перед запуском.')
      } else setError('Не удалось подтвердить запуск. Не создавайте новую задачу: кнопка «Проверить запуск» повторит запрос с тем же идентификатором без повторного списания.')
    } finally { submitLock.current = false; setSending(false) }
  }
  const startNew = () => {
    if (!result || result.status === 'unknown') return
    setRequestId(newId()); setAttempted(false); frozenRequest.current = null; setResult(null); setQuoteState(null); setError('')
  }
  const mediaProps = { disabled: locked, onBusy, onError: setError }
  const videos = recipe.reference_video_urls || []
  const unknown = attempted && (!result || result.status === 'unknown')
  return <div className="min-w-0 space-y-4" data-testid="wan3-prime-form">
    {modelSelector ? <section className={CARD}><h3 className="text-sm font-medium">Модель</h3>{modelSelector}</section> : null}
    <section className={CARD}>
      <div><h3 className="font-serif text-lg font-semibold">Wan 3.0 Video Prime</h3><p className="mt-1 text-xs text-muted-foreground">Выберите задачу. Черновики каждого режима сохраняются при переключении.</p></div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-label="Режим Wan">
        {MODES.map(([mode, label]) => <button type="button" key={mode} disabled={locked} aria-pressed={recipe.scenario === mode} onClick={() => selectMode(mode)}
          className={`rounded-xl border px-3 py-2.5 text-left text-xs transition disabled:opacity-50 ${recipe.scenario === mode ? 'border-cyan/60 bg-cyan/10 text-foreground' : 'border-border/50 text-muted-foreground hover:bg-secondary'}`}>{label}</button>)}
      </div>
      {recipe.scenario === 'edit' ? <p className="rounded-lg border border-cyan/20 bg-cyan/5 p-3 text-xs leading-relaxed">Video1 — исходник для правки. Опишите, что изменить и что сохранить. Фото и дополнительные видео задают нужные детали. Это генеративное редактирование: точное совпадение каждого кадра и лица не гарантируется.</p> : null}
    </section>
    {isFrames ? <div className="grid min-w-0 gap-3 sm:grid-cols-2">
      <MediaField {...mediaProps} title="Первый кадр" label="Загрузить первый кадр" prefix="Кадр " kind="image" limit={1} values={recipe.first_frame_url ? [recipe.first_frame_url] : []} onChange={urls => patch({ first_frame_url: urls[0] || null })} hint="JPEG, PNG без прозрачности, BMP или WEBP. До 20 MB." />
      {recipe.scenario === 'first_last' ? <MediaField {...mediaProps} title="Последний кадр" label="Загрузить последний кадр" prefix="Кадр " offset={2} kind="image" limit={1} values={recipe.last_frame_url ? [recipe.last_frame_url] : []} onChange={urls => patch({ last_frame_url: urls[0] || null })} /> : null}
    </div> : null}
    {isReferences ? <div className="min-w-0 space-y-3">
      {recipe.scenario === 'edit' ? <MediaField {...mediaProps} title="Исходное видео · Video1" label="Загрузить исходное видео (Video1)" prefix="Video" kind="video" limit={1} values={videos[0] ? [videos[0]] : []}
        onChange={urls => patch({ reference_video_urls: urls[0] ? [urls[0], ...videos.slice(1)] : videos.length > 1 ? ['', ...videos.slice(1)] : [] })} hint="MP4/MOV, 1–15 секунд, до 100 MB. Удаление исходника не превращает дополнительный референс в Video1." /> : null}
      <div className="grid min-w-0 gap-3 lg:grid-cols-2">
        <MediaField {...mediaProps} title="Фото-референсы" label="Загрузить фото-референсы" prefix="Image" kind="image" limit={10} values={recipe.reference_image_urls || []} onChange={urls => patch({ reference_image_urls: urls })} hint="До 10 изображений, 20 MB каждое. Номер соответствует порядку в инструкции." />
        <MediaField {...mediaProps} disabled={locked || (recipe.scenario === 'edit' && !videos[0])} title={recipe.scenario === 'edit' ? 'Дополнительные видео' : 'Видео-референсы'} label="Загрузить видео-референсы" prefix="Video" kind="video" limit={recipe.scenario === 'edit' ? 4 : 5} offset={recipe.scenario === 'edit' ? 2 : 1}
          values={recipe.scenario === 'edit' ? videos.slice(1) : videos} onChange={urls => patch({ reference_video_urls: recipe.scenario === 'edit' ? [videos[0] || '', ...urls] : urls })} hint="До 5 видео вместе с исходником. Каждое 1–15 секунд; суммарно до 15 секунд и 100 MB на файл." />
        <MediaField {...mediaProps} title="Аудио-референсы" label="Загрузить аудио-референсы" prefix="Audio" kind="audio" limit={5} values={recipe.reference_audio_urls || []} onChange={urls => patch({ reference_audio_urls: urls })} hint="WAV/MP3, до 15 MB, 1–15 секунд каждый и до 15 секунд суммарно. Можно использовать только аудио." />
      </div>
      {['reference', 'edit'].includes(recipe.scenario) ? <label className="block space-y-1 text-sm">Дополнительный источник<select aria-label="Дополнительный источник" className={SELECT} disabled={locked} value={extraSource} onChange={event => {
        const kind = event.target.value as 'none' | 'file' | 'link'; setExtraSource(kind)
        patch({ reference_file_urls: kind === 'file' ? recipe.reference_file_urls : [], reference_link_urls: kind === 'link' ? recipe.reference_link_urls : [] })
      }}><option value="none">Без документа и веб-страницы</option><option value="file">Документ</option><option value="link">Веб-страница</option></select></label> : null}
      {recipe.scenario === 'file' || extraSource === 'file' ? <MediaField {...mediaProps} title="Документ" label="Загрузить документ" prefix="Файл " kind="file" limit={1} values={recipe.reference_file_urls || []} onChange={urls => patch({ reference_file_urls: urls, reference_link_urls: [] })} hint="PDF, Word, Excel, PowerPoint, Keynote, Pages, Numbers, TXT, MD. До 100 MB и до 50 страниц для страничных форматов." /> : null}
      {recipe.scenario === 'link' || extraSource === 'link' ? <MediaField {...mediaProps} title="Веб-страница" label="Добавить веб-страницу" prefix="Ссылка " kind="link" limit={1} values={recipe.reference_link_urls || []} onChange={urls => patch({ reference_link_urls: urls, reference_file_urls: [] })} hint="Одна публичная страница без входа в аккаунт. Фото, видео и аудио можно добавить выше." /> : null}
    </div> : null}
    <section className={CARD}>
      <label className="block space-y-2 text-sm"><span>{recipe.scenario === 'edit' ? 'Что изменить в Video1?' : 'Инструкция'}</span>
        <Textarea aria-label="Инструкции Wan" value={recipe.prompt} disabled={locked} onChange={e => patch({ prompt: e.target.value })} rows={5} placeholder={recipe.scenario === 'edit' ? 'Заменить одежду на Image1. Сохранить движения, сцену и камеру Video1.' : 'Опишите результат. Для референсов используйте Image1, Video1, Audio1.'} /></label>
      <p className="text-right text-xs text-muted-foreground">{Array.from(recipe.prompt).length.toLocaleString('ru-RU')} / 20 000</p>
      <fieldset disabled={locked} className="grid min-w-0 grid-cols-2 gap-3">
        <label className="space-y-1 text-xs">Качество<select aria-label="Качество Wan" className={SELECT} value={recipe.resolution} onChange={e => patch({ resolution: e.target.value as Wan3PrimeRecipe['resolution'] })}>{['480P', '720P', '1080P'].map(q => <option key={q}>{q}</option>)}</select></label>
        <label className="space-y-1 text-xs">Формат кадра<select aria-label="Формат Wan" className={SELECT} value={recipe.aspect_ratio} onChange={e => patch({ aspect_ratio: e.target.value as Wan3PrimeRecipe['aspect_ratio'] })}>{RATIOS.map(r => <option key={r} value={r}>{r === 'adaptive' ? 'Автоматически' : r}</option>)}</select></label>
        <label className="space-y-1 text-xs">Длительность<select aria-label="Длительность Wan" className={SELECT} value={recipe.duration} onChange={e => patch({ duration: Number(e.target.value) })}><option value={-1}>Auto — выбирает модель</option>{Array.from({ length: 29 }, (_, i) => i + 2).map(n => <option key={n} value={n}>{n} секунд</option>)}</select></label>
        <label className="space-y-1 text-xs">Seed, необязательно<Input aria-label="Seed Wan" type="number" min={0} max={2147483647} step={1} placeholder="Случайный" value={recipe.seed ?? ''} onChange={e => patch({ seed: e.target.value === '' ? null : Number(e.target.value) })} /></label>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" aria-label="Аудио в результате" checked={recipe.audio} onChange={e => patch({ audio: e.target.checked })} />Аудио в результате</label>
        <label className="flex items-center gap-2 text-xs"><input type="checkbox" aria-label="Проверка контента" checked={recipe.nsfw_checker} onChange={e => patch({ nsfw_checker: e.target.checked })} />Проверка контента</label>
      </fieldset>
      <p className="text-xs leading-relaxed text-muted-foreground">Исходные видеосекунды + длительность результата — не более 30 секунд. Сервер проверит файлы и рассчитает стоимость до запуска.</p>
    </section>
    <section className={CARD} aria-label="Стоимость Wan">
      {disabledReason || issue ? <p className="text-xs text-muted-foreground">{disabledReason || issue}</p> : null}
      {pending > 0 ? <p role="status" className="text-xs">Загружаю и проверяю материалы…</p> : null}
      <Button type="button" variant="outline" disabled={working || attempted || !!issue || !!disabledReason} onClick={() => { void calculate() }}>{quoting ? 'Рассчитываю…' : 'Рассчитать стоимость'}</Button>
      {approved ? <div className="space-y-1 text-sm" role="status">
        <p className="text-xl font-semibold">{approved.admin_free ? 'Без списания бананов для администратора' : `Резерв: ${approved.reserve_cost}🍌`}</p>
        <p className="text-xs text-muted-foreground">Видео-референсы: {approved.source_video_duration_seconds} с · к расчёту до {approved.billing_duration_seconds} с.</p>
        <p className="text-xs text-muted-foreground">{approved.settlement_notice || 'Финальная стоимость — по фактическому результату; неиспользованный резерв возвращается.'}</p>
      </div> : <p className="text-xs text-muted-foreground">Запуск станет доступен после расчёта. Изменение материалов или настроек требует нового расчёта.</p>}
      {error ? <p role="alert" className="break-words text-sm text-destructive">{error}</p> : null}
      {result ? <div role="status" className="space-y-1 rounded-lg border border-border p-3 text-sm"><p>{result.status === 'failed' ? `Генерация не выполнена. Возвращено: ${result.refunded_cost ?? result.reserve_cost}🍌.` : result.status === 'unknown' ? 'Провайдер ещё не подтвердил приём. Проверяем эту же задачу.' : result.status === 'done' ? 'Видео готово.' : 'Видео принято в работу.'}</p><code className="block break-all text-xs">{result.internal_task_id}</code><p className="text-xs text-muted-foreground">Результат появится в истории. Доставка в Telegram зависит от доступности чата.</p></div> : null}
      <Button type="button" className="w-full" disabled={working || !!disabledReason || (attempted && !unknown) || (!attempted && (!approved || !!issue || (!isAdmin && !approved.admin_free && credits < approved.reserve_cost)))} onClick={() => { void launch() }}>{sending ? 'Проверяю…' : unknown ? 'Проверить запуск' : 'Запустить Wan'}</Button>
      {result && result.status !== 'unknown' ? <Button type="button" variant="outline" className="w-full" onClick={startNew}>Новая генерация с этими настройками</Button> : null}
    </section>
  </div>
}
