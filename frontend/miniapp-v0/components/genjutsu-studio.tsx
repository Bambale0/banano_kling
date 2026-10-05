'use client'
// Private expiring media bypasses external image optimization.

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowLeftRight,
  ChevronRight,
  Clapperboard,
  ImagePlus,
  Layers3,
  Plus,
  Sparkles,
  Video as VideoIcon,
  WandSparkles,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  type Asset, type Bootstrap, type Operation, type Plan, type Preset, type Project,
  type Quote, type Recipe, type Run, type Step, freshPlan, freshStep, genjutsuCall, launchKey,
  operationLabels, roleLabels, statusLabels, uploadGenjutsu,
} from '@/lib/genjutsu-api'
import { GenjutsuAdmin } from './genjutsu-admin'
import { GenjutsuVideoRange, fullVideoRange, inspectVideoRange, videoSeconds, type VideoRange } from './genjutsu-video-range'

const field = 'w-full rounded-2xl border border-white/10 bg-white/[0.035] px-4 py-3 text-[15px] text-foreground outline-none transition focus:border-white/20 focus:bg-white/[0.055]'
const section = 'rounded-[26px] border border-white/[0.08] bg-white/[0.025] p-4 space-y-3'
const label = 'block space-y-2 text-[13px] font-medium text-muted-foreground'
const uploadCard = 'flex min-h-[92px] w-full items-center gap-3 rounded-[22px] border border-dashed border-white/15 bg-white/[0.025] px-4 py-3 text-left transition active:scale-[0.995]'
const operationCopy: Record<Operation, { title: string; description: string; example: string; icon: typeof Sparkles }> = {
  motion_transfer: { title: 'Перенос движения', description: 'Сохраните движение и камеру, создайте новую сцену.', example: 'Новый образ', icon: Clapperboard },
  object_swap: { title: 'Замена объектов', description: 'Замените героя, одежду, предмет или окружение.', example: 'Другой герой или предмет', icon: ArrowLeftRight },
  restyle: { title: 'Стилизация', description: 'Измените визуальный стиль видео с готовым пресетом.', example: 'Новый стиль', icon: WandSparkles },
}
const terminal = new Set(['completed', 'failed', 'canceled', 'partial'])

export function GenjutsuStudio({ initial = {}, onClose }: {
  initial?: { task_id?: string; run_id?: string; recipe_id?: string; admin?: boolean }; onClose: () => void
}) {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null)
  const [plan, setPlan] = useState<Plan>(freshPlan)
  const [title, setTitle] = useState('Новая работа')
  const [project, setProject] = useState<Project | null>(null)
  const [assets, setAssets] = useState<Asset[]>([])
  const [presets, setPresets] = useState<Preset[]>([])
  const [presetSearch, setPresetSearch] = useState('')
  const [favorites, setFavorites] = useState<string[]>([])
  const [favoritesOnly, setFavoritesOnly] = useState(false)
  const [quote, setQuote] = useState<Quote | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [busy, setBusy] = useState('')
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'editor' | 'history' | 'admin'>(initial.admin ? 'admin' : 'editor')
  const [versions, setVersions] = useState<{ revision: number; title: string }[]>([])
  const [trim, setTrim] = useState<(VideoRange & { assetId: string }) | null>(null)
  const inputRevision = useRef(0)
  const [ack, setAck] = useState(false)
  const [compare, setCompare] = useState(false)
  const [recipe, setRecipe] = useState<Recipe | null>(null)
  const [recipeSource, setRecipeSource] = useState<Asset | null>(null)
  const [recipeAssets, setRecipeAssets] = useState<Array<Asset | null>>([])
  const [recipeValues, setRecipeValues] = useState<Record<string, string>>({})
  const [recipeSourceBinding, setRecipeSourceBinding] = useState<'user' | 'fixed'>('user')
  const [recipeFieldLabels, setRecipeFieldLabels] = useState('')
  const [publishedRecipe, setPublishedRecipe] = useState<Recipe | null>(null)
  const current = useRef({ plan, title, project })
  current.current = { plan, title, project }
  const saved = useRef('')
  const pendingSave = useRef<Promise<Project> | null>(null)
  const alive = useRef(true)
  const video = assets.find(a => a.id === plan.source_asset_id)
  const sourceVideo = recipe ? recipeSource : video
  const sourceCapability = bootstrap?.catalog[recipe?.steps[0]?.operation || plan.steps[0]?.operation]
  const selectedRange = trim?.assetId === sourceVideo?.id ? trim : fullVideoRange(sourceVideo)
  const rangeState = inspectVideoRange(sourceVideo, selectedRange || fullVideoRange(sourceVideo), sourceCapability)
  const missingSource = Boolean(!recipe && plan.source_asset_id && !sourceVideo)
  const rangeNeedsAction = missingSource || Boolean(sourceVideo && (rangeState.error || rangeState.changed))
  const needsPolling = Boolean(run && ((run.state !== 'review' && !terminal.has(run.state)) || run.steps.some(s => ['pending', 'sending'].includes(s.delivery_status || ''))))
  const limit = (key: string, fallback: number) => Number(bootstrap?.limits[key] ?? fallback)

  const refresh = useCallback(async () => {
    const value = await genjutsuCall<Bootstrap>('bootstrap')
    if (alive.current) {
      setBootstrap(value)
      setAssets(previous => {
        const active = previous.find(asset => asset.id === current.current.plan.source_asset_id)
        return active && !value.assets.some(asset => asset.id === active.id) ? [...value.assets, active] : value.assets
      })
    }
    return value
  }, [])

  const message = (cause: unknown) => cause instanceof Error ? cause.message : 'Операция не выполнена.'
  useEffect(() => {
    if (bootstrap && tab === 'admin' && !bootstrap.is_admin) setTab('editor')
  }, [bootstrap, tab])
  async function action(name: string, work: () => Promise<void>) {
    if (busy) return
    setBusy(name); setError(''); setNotice('')
    try { await work() } catch (cause) { if (alive.current) setError(message(cause)) }
    finally { if (alive.current) setBusy('') }
  }

  useEffect(() => {
    alive.current = true
    void refresh().then(async () => {
      if (initial.run_id) {
        const value = await genjutsuCall<{ run: Run }>('run', { run_id: initial.run_id })
        if (alive.current) { setRun(value.run); setTab('history') }
      } else if (initial.task_id) {
        const value = await genjutsuCall<{ asset: Asset }>('import', { task_id: initial.task_id })
        if (alive.current) {
          setAssets(prev => [value.asset, ...prev]); setPlan(prev => ({ ...prev, source_asset_id: value.asset.id }))
        }
      } else if (initial.recipe_id) {
        const value = await genjutsuCall<{ recipe: Recipe }>('recipe_get', { recipe_id: initial.recipe_id })
        if (alive.current) {
          setRecipe(value.recipe)
          setRecipeSource(null)
          setRecipeAssets(Array(value.recipe.slots.length).fill(null))
          setRecipeValues(Object.fromEntries(value.recipe.user_fields.map(field => [field.key, ''])))
          setTitle(value.recipe.title)
        }
      }
    }).catch(cause => { if (alive.current) setError(message(cause)) })
    try { setFavorites(JSON.parse(localStorage.getItem('genjutsu-favorite-presets') || '[]')) } catch { /* Optional preference. */ }
    return () => { alive.current = false }
  }, [refresh, initial.run_id, initial.task_id, initial.recipe_id])

  const needsPresets = plan.steps.some(s => s.operation === 'restyle')
  useEffect(() => {
    if (!needsPresets || !bootstrap?.configured) return
    let active = true
    void genjutsuCall<{ items: Preset[] }>('presets').then(value => { if (active) setPresets(value.items) })
      .catch(cause => { if (active) setError(message(cause)) })
    return () => { active = false }
  }, [needsPresets, bootstrap?.configured])

  useEffect(() => {
    const close = () => { void action('close', async () => {
      if (current.current.plan.source_asset_id && bootstrap?.enabled) await saveCurrent()
      onClose()
    }) }
    window.addEventListener('genjutsu:request-close', close)
    return () => window.removeEventListener('genjutsu:request-close', close)
    // The handler reads the latest draft through current.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, bootstrap?.enabled, onClose])

  async function saveCurrent(): Promise<Project> {
    if (pendingSave.current) await pendingSave.current
    const value = current.current
    const stamp = JSON.stringify([value.title, value.plan])
    if (value.project && saved.current === stamp) return value.project
    setSaving(true)
    const request = genjutsuCall<{ project: Project }>('save_project', {
      title: value.title, plan: value.plan,
      ...(value.project ? { project_id: value.project.id, expected_revision: value.project.revision } : {}),
    }).then(result => {
      current.current.project = result.project
      saved.current = stamp
      if (alive.current) { setProject(result.project); setNotice('Черновик сохранён') }
      return result.project
    })
    pendingSave.current = request
    try { return await request }
    finally { if (pendingSave.current === request) pendingSave.current = null; if (alive.current) setSaving(false) }
  }

  useEffect(() => {
    if (!bootstrap?.enabled || !plan.source_asset_id || busy || quote) return
    const timer = setTimeout(() => { void saveCurrent().catch(cause => setError(message(cause))) }, 1100)
    return () => clearTimeout(timer)
    // saveCurrent reads the current draft through refs; its identity is intentionally irrelevant.
  }, [plan, title, bootstrap?.enabled, busy, quote])

  useEffect(() => {
    if (!run || !needsPolling) return
    let active = true; let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const value = await genjutsuCall<{ run: Run }>('run', { run_id: run.id })
        if (active) setRun(value.run)
      } catch (cause) { if (active) setError(message(cause)) }
      if (active) timer = setTimeout(poll, limit('poll_seconds', 5) * 1000)
    }
    timer = setTimeout(poll, limit('poll_seconds', 5) * 1000)
    return () => { active = false; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, needsPolling])

  function invalidateQuote() { inputRevision.current += 1; setQuote(null); setAck(false) }
  function edit(next: Plan) {
    if (next.source_asset_id !== current.current.plan.source_asset_id) setTrim(null)
    current.current.plan = next; setPlan(next); invalidateQuote(); setError('')
  }
  function changeRange(next: VideoRange) {
    if (!sourceVideo) return
    setTrim({ ...next, assetId: sourceVideo.id }); invalidateQuote(); setError('')
  }
  async function applyRange() {
    if (!sourceVideo || rangeState.error || !rangeState.changed) return
    const revision = inputRevision.current
    const result = await genjutsuCall<{ asset: Asset }>('trim', {
      asset_id: sourceVideo.id, start_ms: rangeState.startMs, end_ms: rangeState.endMs,
    })
    if (!alive.current || revision !== inputRevision.current) return
    setAssets(prev => [result.asset, ...prev.filter(asset => asset.id !== result.asset.id)])
    setTrim(null)
    if (recipe) { setRecipeSource(result.asset); invalidateQuote() }
    else edit({ ...current.current.plan, source_asset_id: result.asset.id })
    const prepared = inspectVideoRange(result.asset, fullVideoRange(result.asset), sourceCapability)
    if (prepared.error) setError(prepared.error)
    else setNotice(`Фрагмент подготовлен: ${videoSeconds(result.asset.duration_ms || 0)} с. Рассчитайте стоимость.`)
  }
  function patchStep(index: number, patch: Partial<Step>) {
    edit({ ...plan, steps: plan.steps.map((s, i) => i === index ? { ...s, ...patch } : s) })
  }
  function favorite(id: string) {
    const next = favorites.includes(id) ? favorites.filter(v => v !== id) : [...favorites, id]
    setFavorites(next)
    try { localStorage.setItem('genjutsu-favorite-presets', JSON.stringify(next)) } catch { /* Optional preference. */ }
  }
  async function newWork(next = freshPlan(), source?: Asset) {
    if (current.current.plan.source_asset_id && bootstrap?.enabled) await saveCurrent()
    current.current = { project: null, title: 'Новая работа', plan: next }
    if (source?.id === next.source_asset_id) setAssets(prev => [source, ...prev.filter(asset => asset.id !== source.id)])
    invalidateQuote(); setTrim(null)
    saved.current = ''; setRecipe(null); setRecipeSource(null); setRecipeAssets([]); setRecipeValues({}); setPublishedRecipe(null)
    setProject(null); setTitle('Новая работа'); setPlan(next); setQuote(null); setTab('editor'); setVersions([])
  }
  async function openProject(id: string, revision?: number) {
    if (current.current.plan.source_asset_id && bootstrap?.enabled) await saveCurrent()
    const value = await genjutsuCall<{ project: Project; source_asset?: Pick<Asset, 'id' | 'kind' | 'duration_ms'> | null }>('project', { project_id: id, ...(revision ? { revision } : {}) })
    const latest = revision ? await genjutsuCall<{ project: Project }>('project', { project_id: id }) : value
    // Restoring a snapshot creates a new version, never writes over history.
    const restored = { ...value.project, revision: latest.project.revision }
    if (value.source_asset?.id === restored.plan.source_asset_id) {
      const source = value.source_asset
      setAssets(prev => {
        const existing = prev.find(asset => asset.id === source.id)
        return [{ ...existing, ...source, url: existing?.url || null }, ...prev.filter(asset => asset.id !== source.id)]
      })
    }
    current.current = { project: restored, title: restored.title, plan: restored.plan }
    saved.current = revision ? '' : JSON.stringify([restored.title, restored.plan])
    invalidateQuote(); setTrim(null)
    setProject(restored); setPlan(restored.plan); setTitle(restored.title); setQuote(null); setTab('editor')
    setVersions((await genjutsuCall<{ items: { revision: number; title: string }[] }>('versions', { project_id: id })).items)
  }
  async function upload(files: FileList | null, kind: Asset['kind'], stepIndex?: number) {
    if (!files?.length) return
    const items = Array.from(files)
    if (stepIndex !== undefined) {
      const step = current.current.plan.steps[stepIndex]
      if (items.length + step.references.length > (bootstrap?.catalog[step.operation].max_images || 0)) throw new Error('Слишком много референсов для этого режима.')
    }
    // Sequential uploads respect the server's bounded preparation capacity.
    for (const file of items) {
      const asset = await uploadGenjutsu(file, kind)
      setAssets(prev => [asset, ...prev.filter(a => a.id !== asset.id)])
      const value = current.current.plan
      const next = stepIndex === undefined ? { ...value, source_asset_id: asset.id } : {
        ...value, steps: value.steps.map((s, i) => i !== stepIndex ? s : {
          ...s, references: [...s.references, { asset_id: asset.id, role: 'character', label: '', binding: 'user' as const }],
        }),
      }
      edit(next)
    }
  }
  async function uploadRecipeSource(file: File | undefined) {
    if (!file) return
    const asset = await uploadGenjutsu(file, 'video')
    setAssets(prev => [asset, ...prev.filter(item => item.id !== asset.id)])
    setRecipeSource(asset)
    setTrim(null); invalidateQuote()
  }

  async function uploadRecipeReference(file: File | undefined, index: number) {
    if (!file) return
    const asset = await uploadGenjutsu(file, 'image')
    setAssets(prev => [asset, ...prev.filter(item => item.id !== asset.id)])
    setRecipeAssets(current => {
      const next = [...current]
      next[index] = asset
      return next
    })
    invalidateQuote()
  }

  async function quoteRecipe() {
    if (!recipe || (recipe.source_slot && (!recipeSource || rangeNeedsAction)) || recipeAssets.some(asset => !asset)) return
    const revision = inputRevision.current
    const result = await genjutsuCall<{ quote: Quote; recipe: Recipe }>('recipe_quote', {
      recipe_id: recipe.id,
      ...(recipe.source_slot ? { source_asset_id: recipeSource?.id } : {}),
      reference_asset_ids: recipeAssets.map(asset => asset?.id || ''),
      user_values: recipeValues,
    })
    if (!alive.current || revision !== inputRevision.current) return
    setQuote(result.quote)
    setRecipe(result.recipe)
    setAck(false)
  }

  async function publishRecipe() {
    if (!bootstrap?.is_admin) return
    const savedProject = await saveCurrent()
    const latest = await refresh()
    const verification = (
      run?.state === 'completed' && run.admin_free && run.project_id === savedProject.id
        ? run
        : latest.runs.find(item => item.state === 'completed' && item.project_id === savedProject.id)
    )
    if (!verification) {
      throw new Error('Сначала выполните успешный тестовый запуск этого проекта в Genjutsu, затем публикуйте рецепт.')
    }
    const labels = recipeFieldLabels.split(',').map(value => value.replace(/[{}]/g, '').trim()).filter(Boolean).slice(0, 6)
    const value = await genjutsuCall<{ recipe: Recipe }>('recipe_publish', {
      project_id: savedProject.id,
      revision: savedProject.revision,
      title: savedProject.title,
      user_fields: labels.map(label => ({ key: label.slice(0, 48), label: label.slice(0, 64) })),
      verification_run_id: verification.id,
      source_binding: recipeSourceBinding,
    })
    setPublishedRecipe(value.recipe)
  }

  async function getQuote() {
    if (!sourceVideo || rangeNeedsAction) return
    const revision = inputRevision.current
    const savedProject = await saveCurrent()
    if (!alive.current || revision !== inputRevision.current) return
    const result = await genjutsuCall<{ quote: Quote }>('quote', { project_id: savedProject.id, revision: savedProject.revision })
    if (!alive.current || revision !== inputRevision.current) return
    setQuote(result.quote); setAck(false)
  }
  async function start() {
    if (!quote || rangeNeedsAction) return
    const value = await genjutsuCall<{ run: Run }>('start', {
      quote_id: quote.id, request_key: launchKey(quote.id), acknowledge_provider_cost: ack,
    })
    setRun(value.run); setQuote(null); setTab('history'); await refresh()
  }
  async function runAction(name: string, stepId?: string) {
    if (!run) return
    if (name === 'cancel' && !window.confirm('Остановить незапущенные шаги и запросить отмену остальных? Уже выполненные шаги останутся доступными.')) return
    if (name === 'redeliver' && !window.confirm('Повторить доставку? Если предыдущая отправка дошла без подтверждения, в чате может появиться копия. Генерация и новое списание не выполняются.')) return
    const value = await genjutsuCall<{ run: Run }>(name, {
      run_id: run.id, ...(stepId ? { step_id: stepId } : {}),
      ...(name === 'redeliver' ? { acknowledge_duplicate_risk: true } : {}),
    })
    setRun(value.run)
  }

  const blocked = Boolean(busy || saving)
  const shownPresets = presets.filter(p => (!favoritesOnly || favorites.includes(p.id)) && p.name.toLowerCase().includes(presetSearch.toLowerCase()))
  const primaryStep = plan.steps[0]
  const primaryCaps = bootstrap?.catalog[primaryStep?.operation]

  return <section className="mx-auto min-w-0 w-full max-w-2xl space-y-5 overflow-x-clip pb-28" aria-label="Студия Genjutsu">
    <header className="sticky top-0 z-20 flex min-w-0 items-center justify-between gap-3 border-b border-white/[0.06] bg-background/90 px-1 py-3 backdrop-blur-xl sm:px-2">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1"><span className="inline-flex h-7 items-center rounded-full border border-white/10 bg-white/[0.035] px-2.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">Higgsfield</span><span className="text-lg font-semibold tracking-tight">Genjutsu</span></div>
        <p className="mt-1 truncate text-xs text-muted-foreground">Редактирование видео по референсам</p>
      </div>
      <Button className="shrink-0 rounded-full px-4" variant="ghost" aria-label="Закрыть студию" disabled={blocked} onClick={() => void action('close', async () => { if (plan.source_asset_id && bootstrap?.enabled) await saveCurrent(); onClose() })}>Закрыть</Button>
    </header>
    <nav className="grid grid-cols-2 rounded-[22px] border border-white/[0.06] bg-white/[0.025] p-1" aria-label="Разделы Genjutsu">
      <button type="button" className={`rounded-[18px] px-3 py-2.5 text-sm font-medium transition ${tab === 'editor' ? 'bg-white/10 text-foreground shadow-sm' : 'text-muted-foreground'}`} onClick={() => setTab('editor')}>Создать</button>
      <button type="button" className={`rounded-[18px] px-3 py-2.5 text-sm font-medium transition ${tab === 'history' ? 'bg-white/10 text-foreground shadow-sm' : 'text-muted-foreground'}`} onClick={() => { setTab('history'); void refresh().catch(cause => setError(message(cause))) }}>Мои работы</button>
      {bootstrap?.is_admin && <button type="button" className={`col-span-2 mt-1 rounded-[18px] px-3 py-2.5 text-sm font-medium transition ${tab === 'admin' ? 'bg-white/10 text-foreground shadow-sm' : 'text-muted-foreground'}`} onClick={() => setTab('admin')}>Управление</button>}
    </nav>
    {error && <div role="alert" className="rounded-xl border border-destructive/30 p-3 text-sm text-destructive">{error}</div>}
    <div aria-live="polite" className="text-xs text-muted-foreground">{busy ? 'Выполняется операция…' : saving ? 'Сохраняем черновик…' : notice}</div>
    {!bootstrap ? <Button variant="outline" onClick={() => void action('refresh', async () => { await refresh() })}>Загрузить студию</Button> : <>
      {!bootstrap.configured && <div className={section}>Интеграция ещё не настроена. {bootstrap.is_admin ? `Провайдер: ${bootstrap.provider_ready ? 'подключён' : 'нет ключа'}. Хранилище: ${bootstrap.media_ready ? 'готово' : 'не настроено'}.` : 'Новые генерации пока недоступны.'}</div>}
      {!bootstrap.enabled && <p className={section}>Новые запуски отключены. История и уже принятые работы остаются доступны.</p>}
      {tab === 'admin' && bootstrap.is_admin && <GenjutsuAdmin onChanged={refresh} />}
      {tab === 'editor' && recipe && <div className="space-y-4">
        <div className={section}>
          <p className="text-xs uppercase tracking-widest text-gold">Тренд Genjutsu</p>
          <h3 className="text-lg font-medium">{recipe.title}</h3>
          <p className="text-sm text-muted-foreground">Скрытые настройки и закреплённые материалы хранятся на сервере. Перед запуском вы увидите полную стоимость.</p>
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            {recipe.steps.map((step, index) => <span key={index} className="rounded-full border border-border px-2 py-1">Шаг {index + 1}: {operationLabels[step.operation]} · {step.resolution}</span>)}
          </div>
          {!recipe.source_slot && recipe.current_cost !== null && <p className="text-sm">Текущая стоимость рецепта: <strong>{recipe.current_cost} 🍌</strong></p>}
        </div>
        <fieldset className={`${section} min-w-0`} disabled={!bootstrap.enabled || blocked}>
          <div>
            <h3 className="font-semibold">Референсы тренда</h3>
            <p className="mt-1 text-xs text-muted-foreground">Прикрепите нужные фото и видео здесь — скрытые материалы автора не показываются.</p>
          </div>
          {recipe.source_slot && <div className="space-y-2">
            <label className={uploadCard}>
              <span className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-[16px] bg-white/[0.06]"><VideoIcon className="h-5 w-5" /></span>
              <span className="min-w-0 flex-1"><span className="block truncate font-medium">{recipe.source_slot.label}</span><span className="mt-0.5 block text-xs text-muted-foreground">{recipeSource ? 'Видео загружено — нажмите, чтобы заменить' : 'MP4 или MOV · движение берётся из этого видео'}</span></span>
              <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/[0.07]"><Plus className="h-4 w-4" /></span>
              <input aria-label={recipe.source_slot.label} type="file" accept="video/mp4,video/quicktime,video/*" className="sr-only" onChange={e => { const file = e.target.files?.[0]; void action('recipe-source-upload', () => uploadRecipeSource(file)); e.target.value = '' }} />
            </label>
            {recipeSource?.url && <video src={recipeSource.url} controls playsInline preload="metadata" className="max-h-52 w-full rounded-2xl bg-black object-contain" />}
            {recipeSource && <GenjutsuVideoRange asset={recipeSource} range={selectedRange || fullVideoRange(recipeSource)} capability={sourceCapability} disabled={blocked} onChange={changeRange} onApply={() => void action('recipe-trim', applyRange)} />}
          </div>}
          {recipe.slots.length > 0 && <div className="space-y-3 border-t border-white/[0.06] pt-3">
            {recipe.slots.map((slot, index) => <div key={index} className="space-y-2">
              <label className={uploadCard}>
                <span className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-[16px] bg-white/[0.06]"><ImagePlus className="h-5 w-5" /></span>
                <span className="min-w-0 flex-1"><span className="block truncate font-medium">{slot.label}</span><span className="mt-0.5 block text-xs text-muted-foreground">{recipeAssets[index] ? 'Фото загружено — нажмите, чтобы заменить' : roleLabels[slot.role] || slot.role}</span></span>
                <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/[0.07]"><Plus className="h-4 w-4" /></span>
                <input aria-label={slot.label} type="file" accept="image/*" className="sr-only" onChange={e => { const file = e.target.files?.[0]; void action('recipe-upload', () => uploadRecipeReference(file, index)); e.target.value = '' }} />
              </label>
              {recipeAssets[index]?.url && <img src={recipeAssets[index]?.url || undefined} alt={slot.label} className="h-24 w-24 rounded-xl object-cover" />}
            </div>)}
          </div>}
          {recipe.user_fields.length > 0 && <div className="space-y-3 border-t border-white/[0.06] pt-3">
            {recipe.user_fields.map(fieldSpec => <label key={fieldSpec.key} className={label}>{fieldSpec.label}<input className={field} type={fieldSpec.type === 'number' ? 'number' : fieldSpec.type === 'date' ? 'date' : 'text'} maxLength={fieldSpec.max_length || 160} value={recipeValues[fieldSpec.key] || ''} onChange={e => { setRecipeValues(current => ({ ...current, [fieldSpec.key]: e.target.value })); invalidateQuote() }} required={fieldSpec.required !== false} /></label>)}
          </div>}
          <Button className="h-12 w-full rounded-2xl text-base" disabled={blocked || Boolean(recipe.source_slot && (!recipeSource || rangeNeedsAction)) || recipeAssets.some(asset => !asset) || recipe.user_fields.some(fieldSpec => fieldSpec.required !== false && !(recipeValues[fieldSpec.key] || '').trim())} onClick={() => void action('recipe-quote', quoteRecipe)}>Рассчитать стоимость</Button>
        </fieldset>
        {quote && <div className="space-y-3 rounded-2xl border border-gold/40 bg-gold/5 p-4">
          <h3 className="font-medium">Подтверждение запуска</h3>
          {recipeSource && <p className="text-sm">Длительность видео к запуску: {videoSeconds(recipeSource.duration_ms || 0)} с</p>}
          <p>Резерв: <strong>{bootstrap.is_admin ? '0' : quote.total_credits} бананов</strong>{bootstrap.is_admin && <span className="text-sm text-muted-foreground"> · пользовательский тариф {quote.total_credits}</span>}</p>
          {quote.allocations.map(a => <div key={`${a.variant}:${a.ordinal}`} className="flex justify-between gap-2 text-sm"><span>Вариант {a.variant + 1}, шаг {a.ordinal + 1}: {operationLabels[a.operation]} · {a.maximum_reserve ? 'до ' : ''}{a.billable_seconds} с к оплате</span><span>{a.reserved_credits} 🍌</span></div>)}
          {bootstrap.is_admin && <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />Подтверждаю реальный расход в Higgsfield.</label>}
          <Button disabled={blocked || rangeNeedsAction || !bootstrap.enabled || !bootstrap.configured || (bootstrap.is_admin && !ack)} onClick={() => void action('start', start)}>Запустить тренд</Button>
        </div>}
      </div>}
      {tab === 'editor' && !recipe && <div className="space-y-6">
        <section className="min-w-0 space-y-3">
          <div>
            <h3 className="text-lg font-semibold tracking-tight">Что можно изменить</h3>
            <p className="mt-1 text-sm text-muted-foreground">Выберите сценарий — остальные поля подстроятся автоматически.</p>
          </div>
          <div data-testid="genjutsu-operation-grid" className="grid min-w-0 grid-cols-3 gap-2">
            {(Object.keys(bootstrap.catalog) as Operation[]).map(op => {
              const copy = operationCopy[op]
              const Icon = copy.icon
              const active = primaryStep.operation === op
              return <button key={op} type="button" onClick={() => patchStep(0, { operation: op, preset_id: null })} className={`min-w-0 rounded-[20px] border px-2 py-3 text-center transition active:scale-[0.99] ${active ? 'border-white/25 bg-white/[0.08] text-foreground' : 'border-white/[0.08] bg-white/[0.025] text-muted-foreground'}`}>
                <span className="mx-auto inline-flex h-9 w-9 items-center justify-center rounded-xl bg-white/[0.07]"><Icon className="h-4 w-4" /></span>
                <span className="mt-2 block break-words text-[11px] font-semibold leading-tight sm:text-xs">{copy.example}</span>
              </button>
            })}
          </div>
          <p className="px-1 text-sm text-muted-foreground">{operationCopy[primaryStep.operation].description}</p>
          <label className="sr-only">Операция шага 1<select value={primaryStep.operation} onChange={e => patchStep(0, { operation: e.target.value as Operation, preset_id: null })}>{(Object.keys(bootstrap.catalog) as Operation[]).map(op => <option key={op} value={op}>{operationLabels[op]}</option>)}</select></label>
        </section>

        <details className="group rounded-[22px] border border-white/[0.06] bg-white/[0.02] px-4 py-3">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium"><span className="flex items-center gap-2"><Layers3 className="h-4 w-4 text-muted-foreground" />Проект и черновики</span><ChevronRight className="h-4 w-4 text-muted-foreground transition group-open:rotate-90" /></summary>
          <div className="mt-4 space-y-3">
            <div className="flex gap-2"><Button disabled={blocked} variant="outline" onClick={() => void action('new', () => newWork())}>Новый проект</Button>
              <label className="min-w-0 flex-1"><span className="sr-only">Открыть проект</span><select className={field} disabled={blocked} value={project?.id || ''} onChange={e => e.target.value && void action('open', () => openProject(e.target.value))}><option value="">Черновики и проекты</option>{bootstrap.projects.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select></label></div>
            <label className={label}>Название работы<input className={field} value={title} maxLength={120} onChange={e => { current.current.title = e.target.value; setTitle(e.target.value); invalidateQuote() }} /></label>
            {project && <p className="text-xs text-muted-foreground">Версия {project.revision} · изменения сохраняются автоматически</p>}
            {versions.length > 1 && <label className={label}>Восстановить версию<select className={field} value="" disabled={blocked} onChange={e => e.target.value && project && void action('restore', () => openProject(project.id, Number(e.target.value)))}><option value="">Выбрать сохранённую версию</option>{versions.map(v => <option key={v.revision} value={v.revision}>{v.revision}: {v.title}</option>)}</select></label>}
          </div>
        </details>

        <fieldset className="space-y-6" disabled={!bootstrap.enabled || Boolean(busy)}>
          <section className="space-y-3">
            <div className="flex items-end justify-between gap-3"><div><h3 className="font-semibold">Видео с нужным движением</h3><p className="mt-1 text-xs text-muted-foreground">{primaryCaps ? `${primaryCaps.minimum_video_ms / 1000}–${primaryCaps.maximum_video_ms / 1000} секунд` : 'Видео'}</p></div>{video && <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-muted-foreground">{((video.duration_ms || 0) / 1000).toFixed(1)} сек.</span>}</div>
            <label className={uploadCard}>
              <span className="inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-[18px] bg-white/[0.06]"><VideoIcon className="h-6 w-6" /></span>
              <span className="min-w-0 flex-1"><span className="block font-medium">{video ? 'Заменить видео' : 'Добавить видео'}</span><span className="mt-1 block text-sm text-muted-foreground">MP4 или MOV</span></span>
              <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/[0.07]"><Plus className="h-5 w-5" /></span>
              <input type="file" accept="video/*" className="sr-only" onChange={e => { const files = e.target.files; void action('upload', () => upload(files, 'video')); e.target.value = '' }} />
            </label>
            <label className={label}>Видео из библиотеки<select className={field} value={plan.source_asset_id} onChange={e => edit({ ...plan, source_asset_id: e.target.value })}><option value="">Выберите исходник</option>{assets.filter(a => a.kind === 'video').map(a => <option key={a.id} value={a.id}>Видео {a.id.slice(0, 6)} · {((a.duration_ms || 0) / 1000).toFixed(2)} с</option>)}</select></label>
            {video && <div className="overflow-hidden rounded-[24px] border border-white/[0.08] bg-black"><video key={video.url} src={video.url || undefined} controls playsInline preload="metadata" className="max-h-[360px] w-full bg-black" /></div>}
            {missingSource && <p role="alert" className="text-sm text-destructive">Исходное видео недоступно. Выберите его из библиотеки или загрузите снова.</p>}
            {video && <GenjutsuVideoRange asset={video} range={selectedRange || fullVideoRange(video)} capability={sourceCapability} disabled={blocked} onChange={changeRange} onApply={() => void action('trim', applyRange)} />}
          </section>

          {primaryCaps && <section className="space-y-3">
            <div className="flex items-end justify-between gap-3"><div><h3 className="font-semibold">{primaryStep.operation === 'restyle' ? 'Фото персонажей' : 'Фото для новой сцены'}</h3><p className="mt-1 text-xs text-muted-foreground">{primaryStep.operation === 'restyle' ? 'Необязательно — можно стилизовать героев исходного видео' : 'Персонаж, одежда или предмет'}</p></div><span className="text-xs text-muted-foreground">{primaryStep.references.length}/{primaryCaps.max_images}</span></div>
            <label className={uploadCard}>
              <span className="inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-[18px] bg-white/[0.06]"><ImagePlus className="h-6 w-6" /></span>
              <span className="min-w-0 flex-1"><span className="block font-medium">Добавить фото</span><span className="mt-1 block text-sm text-muted-foreground">До {primaryCaps.max_images} фотографий того, что хотите увидеть</span></span>
              <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white/[0.07]"><Plus className="h-5 w-5" /></span>
              <input type="file" multiple accept="image/*" className="sr-only" onChange={e => { const files = e.target.files; void action('references', () => upload(files, 'image', 0)); e.target.value = '' }} />
            </label>
            <label className={label}>Добавить из моей библиотеки<select aria-label="Добавить референс к шагу 1" className={field} value="" onChange={e => { if (e.target.value) patchStep(0, { references: [...primaryStep.references, { asset_id: e.target.value, role: 'character', label: '', binding: 'user' as const }] }) }} disabled={primaryStep.references.length >= primaryCaps.max_images}><option value="">Выберите сохранённое фото</option>{assets.filter(a => a.kind === 'image' && !primaryStep.references.some(r => r.asset_id === a.id)).map(a => <option key={a.id} value={a.id}>Фото {a.id.slice(0, 8)}</option>)}</select></label>
            {primaryStep.references.length > 0 && <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">{primaryStep.references.map((ref, refIndex) => { const asset = assets.find(a => a.id === ref.asset_id); return <div key={ref.asset_id} className="group relative aspect-square overflow-hidden rounded-[18px] border border-white/[0.08] bg-white/[0.03]">{asset?.url ? <img src={asset.url} alt={`Референс ${refIndex + 1}`} className="h-full w-full object-cover" /> : <span className="flex h-full items-center justify-center text-xs text-muted-foreground">Фото {refIndex + 1}</span>}<button type="button" aria-label={`Убрать референс ${refIndex + 1}`} className="absolute right-1.5 top-1.5 inline-flex h-7 w-7 items-center justify-center rounded-full bg-black/70 text-sm text-white" onClick={() => patchStep(0, { references: primaryStep.references.filter((_, i) => i !== refIndex) })}>×</button></div>})}</div>}
            {primaryStep.references.length > 0 && <details className="group rounded-[20px] border border-white/[0.06] bg-white/[0.02] px-4 py-3"><summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium">Точно настроить референсы<ChevronRight className="h-4 w-4 text-muted-foreground transition group-open:rotate-90" /></summary><div className="mt-4 space-y-3">{primaryStep.references.map((ref, refIndex) => <div key={ref.asset_id} className="space-y-2 rounded-2xl border border-white/[0.06] p-3"><select aria-label={`Роль референса ${refIndex + 1} шага 1`} className={field} value={ref.role} onChange={e => patchStep(0, { references: primaryStep.references.map((r, i) => i === refIndex ? { ...r, role: e.target.value } : r) })}>{!primaryCaps.roles.includes(ref.role) && <option value={ref.role}>{roleLabels[ref.role]} — не поддерживается</option>}{primaryCaps.roles.map(role => <option key={role} value={role}>{roleLabels[role] || role}</option>)}</select>{bootstrap.is_admin && <label className={label}>В тренде<select className={field} value={ref.binding || 'user'} onChange={e => patchStep(0, { references: primaryStep.references.map((r, i) => i === refIndex ? { ...r, binding: e.target.value as 'user' | 'fixed' } : r) })}><option value="user">Пользователь заменяет</option><option value="fixed">Закреплённый референс</option></select></label>}<input aria-label={`Назначение референса ${refIndex + 1} шага 1`} className={field} maxLength={200} placeholder="Например: герой слева" value={ref.label} onChange={e => patchStep(0, { references: primaryStep.references.map((r, i) => i === refIndex ? { ...r, label: e.target.value } : r) })} /></div>)}</div></details>}
            {(primaryStep.references.some(ref => !primaryCaps.roles.includes(ref.role)) || primaryStep.references.length > primaryCaps.max_images) && <p role="alert" className="text-sm text-destructive">Референсы сохранены, но не подходят выбранному режиму. Измените роли или количество.</p>}
          </section>}

          {primaryStep.operation === 'restyle' && <section className="space-y-3"><div><h3 className="font-semibold">Стиль</h3><p className="mt-1 text-xs text-muted-foreground">Выберите визуальный пресет</p></div><label className={label}>Поиск стиля<input className={field} value={presetSearch} onChange={e => setPresetSearch(e.target.value)} /></label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={favoritesOnly} onChange={e => setFavoritesOnly(e.target.checked)} />Только избранные</label><div className="grid max-h-80 grid-cols-2 gap-2 overflow-auto sm:grid-cols-3">{shownPresets.map(p => <div key={p.id} className={`overflow-hidden rounded-[20px] border p-2 ${primaryStep.preset_id === p.id ? 'border-white/30 bg-white/[0.06]' : 'border-white/[0.08]'}`}><button type="button" aria-pressed={primaryStep.preset_id === p.id} className="w-full text-left text-xs" onClick={() => patchStep(0, { preset_id: p.id })}><img src={p.preview_url} alt="" loading="lazy" className="mb-2 aspect-video w-full rounded-[14px] object-cover" /><span className="font-medium">{p.name}</span></button><button type="button" className="mt-2 text-xs text-muted-foreground" onClick={() => favorite(p.id)}>{favorites.includes(p.id) ? '★ В избранном' : '☆ В избранное'}</button></div>)}</div>{!presets.length && <p className="text-sm text-muted-foreground">Каталог стилей пока недоступен.</p>}{primaryStep.preset_id && !presets.some(p => p.id === primaryStep.preset_id) && <p role="alert" className="text-sm text-destructive">Сохранённый стиль не найден. Выберите доступный стиль.</p>}</section>}

          <section className="space-y-3">
            <label className="block space-y-2"><span className="text-base font-semibold">Что изменить?</span><textarea className={`${field} min-h-[138px] resize-none`} rows={4} maxLength={primaryCaps?.max_prompt_length || 4000} value={primaryStep.prompt} onChange={e => patchStep(0, { prompt: e.target.value })} placeholder={primaryStep.operation === 'motion_transfer' ? 'Например, перенесите движения героя на персонажа с фото. Сохраните композицию и камеру.' : primaryStep.operation === 'object_swap' ? 'Например, замените одежду героя на образ с фото, сохранив лицо, позу и движение.' : 'Опишите желаемый стиль и то, что важно сохранить.'} /></label>
          </section>

          {primaryCaps && <section className="space-y-3">
            <div className="flex items-center justify-between"><h3 className="font-semibold">Качество</h3><span className="text-xs text-muted-foreground">Длительность и формат — из видео</span></div>
            <div className={`grid gap-1 rounded-[20px] border border-white/[0.06] bg-white/[0.025] p-1 ${primaryCaps.resolutions.length === 3 ? 'grid-cols-3' : primaryCaps.resolutions.length === 2 ? 'grid-cols-2' : 'grid-cols-1'}`}>{primaryCaps.resolutions.map(resolution => <button key={resolution} type="button" className={`rounded-[16px] px-3 py-3 text-sm font-medium transition ${primaryStep.resolution === resolution ? 'bg-white/10 text-foreground shadow-sm' : 'text-muted-foreground'}`} onClick={() => patchStep(0, { resolution })}>{resolution}</button>)}</div>
            <label className="sr-only">Качество шага 1<select value={primaryStep.resolution} onChange={e => patchStep(0, { resolution: e.target.value })}>{primaryCaps.resolutions.map(v => <option key={v}>{v}</option>)}</select></label>
          </section>}

          <details className="group rounded-[22px] border border-white/[0.06] bg-white/[0.02] px-4 py-3"><summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium"><span className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-muted-foreground" />Что сохранить и дополнительные настройки</span><ChevronRight className="h-4 w-4 text-muted-foreground transition group-open:rotate-90" /></summary><div className="mt-4 space-y-4"><label className={label}>Что сохранить<input className={field} maxLength={2000} value={primaryStep.preserve} onChange={e => patchStep(0, { preserve: e.target.value })} placeholder="Например: лицо, движение камеры и фон" /></label><label className={label}>Количество вариантов<input className={field} type="number" min={1} max={limit('max_variants', 1)} value={plan.variants} onChange={e => edit({ ...plan, variants: Number(e.target.value) })} /></label>{plan.steps.length > 1 && <label className={label}>Продолжение цепочки<select className={field} value={plan.continuation} onChange={e => edit({ ...plan, continuation: e.target.value as Plan['continuation'] })}><option value="automatic">Автоматически</option><option value="manual">Подтверждать следующий шаг</option></select></label>}<div className="flex flex-wrap gap-2"><Button variant="outline" disabled={blocked || !plan.source_asset_id} onClick={() => void action('save', async () => { await saveCurrent(); await refresh() })}>Сохранить проект</Button><Button variant="outline" disabled={plan.steps.length >= limit('max_steps', 1)} onClick={() => edit({ ...plan, steps: [...plan.steps, freshStep()] })}>Добавить шаг</Button></div>{bootstrap.is_admin && <div className="space-y-2 rounded-2xl border border-white/[0.06] p-3"><p className="text-sm font-medium">Рецепт для «Трендов»</p><p className="text-xs text-muted-foreground">Закреплённые refs остаются скрытыми от пользователя.</p><label className={label}>Видео тренда<select className={field} value={recipeSourceBinding} onChange={e => setRecipeSourceBinding(e.target.value as 'user' | 'fixed')}><option value="user">Пользователь загружает своё видео</option><option value="fixed">Оставить видео автора скрытым</option></select></label><input className={field} value={recipeFieldLabels} onChange={e => setRecipeFieldLabels(e.target.value)} placeholder="Имя, Возраст, Надпись" /><Button type="button" variant="outline" disabled={blocked || !plan.source_asset_id} onClick={() => void action('publish-recipe', publishRecipe)}>Создать приватный рецепт</Button>{publishedRecipe && <p className="break-all text-xs">Рецепт готов: <strong>{publishedRecipe.id}</strong> · фото: {publishedRecipe.slots.length}{publishedRecipe.current_cost !== null ? ` · ${publishedRecipe.current_cost} 🍌` : ''}</p>}</div>}</div></details>

          {plan.steps.slice(1).map((step, offset) => {
            const index = offset + 1
            const caps = bootstrap.catalog[step.operation]
            return <section key={index} className={section}><div className="flex items-center justify-between"><div><p className="text-xs text-muted-foreground">Дополнительный шаг {index + 1}</p><h3 className="font-medium">{operationLabels[step.operation]}</h3></div><Button size="sm" variant="ghost" onClick={() => edit({ ...plan, steps: plan.steps.filter((_, i) => i !== index) })}>Убрать</Button></div><div className="grid gap-3 sm:grid-cols-2"><label className={label}>Операция шага {index + 1}<select className={field} value={step.operation} onChange={e => patchStep(index, { operation: e.target.value as Operation, preset_id: null })}>{(Object.keys(bootstrap.catalog) as Operation[]).map(op => <option key={op} value={op}>{operationLabels[op]}</option>)}</select></label><label className={label}>Качество шага {index + 1}<select className={field} value={step.resolution} onChange={e => patchStep(index, { resolution: e.target.value })}>{caps.resolutions.map(v => <option key={v}>{v}</option>)}</select></label></div><label className={label}>Что изменить — шаг {index + 1}<textarea className={field} rows={3} value={step.prompt} onChange={e => patchStep(index, { prompt: e.target.value })} /></label></section>
          })}
        </fieldset>

        {quote && <div className="space-y-3 rounded-[26px] border border-white/10 bg-white/[0.035] p-4"><div className="flex items-center justify-between gap-3"><div><p className="text-xs text-muted-foreground">К запуску</p><h3 className="text-lg font-semibold">{bootstrap.is_admin ? 'Тестовый запуск' : `${quote.total_credits} бананов`}</h3></div><span className="text-xs text-muted-foreground">до {new Date(quote.expires_ms).toLocaleTimeString()}</span></div>{bootstrap.is_admin && <p className="text-sm">С вашего баланса: <strong>0 бананов</strong>. Пользовательский тариф: {quote.total_credits} бананов. Реальный расход Higgsfield подтверждается ниже.</p>}{video && <p className="text-sm">Длительность видео к запуску: {videoSeconds(video.duration_ms || 0)} с</p>}{quote.allocations.map(a => <div key={`${a.variant}:${a.ordinal}`} className="flex justify-between gap-2 text-sm text-muted-foreground"><span>Вариант {a.variant + 1}, шаг {a.ordinal + 1} · {a.maximum_reserve ? 'до ' : ''}{a.billable_seconds} с к оплате</span><span>{a.reserved_credits} 🍌</span></div>)}{bootstrap.is_admin && <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />Подтверждаю реальный расход в Higgsfield.</label>}<Button className="h-12 w-full rounded-2xl text-base" disabled={blocked || rangeNeedsAction || !bootstrap.enabled || !bootstrap.configured || (bootstrap.is_admin && !ack)} onClick={() => void action('start', start)}>Запустить</Button></div>}

        {!quote && <div className="sticky bottom-3 z-10 rounded-[24px] border border-white/10 bg-background/90 p-2 shadow-2xl backdrop-blur-xl"><Button className="h-12 w-full rounded-[18px] text-base" disabled={blocked || !plan.source_asset_id || rangeNeedsAction} onClick={() => void action('quote', getQuote)}>Рассчитать стоимость</Button></div>}
      </div>}
      {tab === 'history' && <div className="space-y-4">
        <div className="flex flex-wrap gap-2">{bootstrap.runs.map(item => <Button key={item.id} variant={run?.id === item.id ? 'default' : 'outline'} size="sm" disabled={blocked} onClick={() => void action('run', async () => { setRun((await genjutsuCall<{ run: Run }>('run', { run_id: item.id })).run) })}>{new Date(item.created_ms).toLocaleDateString()} · {statusLabels[item.state] || item.state} · {item.id.slice(0, 6)}</Button>)}</div>
        {!bootstrap.runs.length && !run && <p className={section}>Здесь появятся принятые задачи. Черновики доступны в разделе «Создать».</p>}
        {run && <div className={section}>
          <div className="flex flex-wrap items-center justify-between gap-2"><div><h3>{statusLabels[run.state] || run.state}</h3><p className="break-all text-xs text-muted-foreground">{run.id}</p></div><Button variant="outline" disabled={blocked} onClick={() => void action('refresh-run', async () => { setRun((await genjutsuCall<{ run: Run }>('run', { run_id: run.id })).run) })}>Обновить статус</Button></div>
          <div className="flex flex-wrap gap-2">{!terminal.has(run.state) && <Button variant="outline" disabled={blocked || Boolean(run.cancel_requested)} onClick={() => void action('cancel', () => runAction('cancel'))}>Отменить оставшиеся шаги</Button>}
            {run.plan && <Button variant="outline" disabled={blocked} onClick={() => void action('repeat', async () => {
              const source = run.steps.find(step => step.source_asset?.id === run.plan?.source_asset_id)?.source_asset
              await newWork(run.plan, source)
            })}>Повторить с настройками</Button>}
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={compare} onChange={e => setCompare(e.target.checked)} />Показать исходник рядом</label></div>
          {run.steps.map(step => <article key={step.id} className="space-y-2 border-t border-border pt-3">
            <h4 className="text-sm font-medium">Вариант {step.variant + 1} · шаг {step.ordinal + 1} · {operationLabels[step.spec.operation]} · {step.spec.resolution}</h4>
            <p className="text-sm">{statusLabels[step.status] || step.status}</p>
            <p className="text-xs text-muted-foreground">Резерв {step.reserved_credits} 🍌 · возврат {step.refunded_credits} 🍌{step.actual_credits !== null ? ` · расчёт ${step.actual_credits} 🍌` : ''}</p>
            {step.error_code && <p className="break-all text-xs text-destructive">Код: {step.error_code}. Результаты остальных шагов не потеряны.</p>}
            <div className={compare ? 'grid gap-2 sm:grid-cols-2' : ''}>{compare && step.source_asset?.url && <div><p className="text-xs">Исходник</p><video src={step.source_asset.url} controls playsInline preload="metadata" className="max-h-80 w-full rounded-xl bg-black" /></div>}{step.output_asset?.url && <div><p className="text-xs">Результат</p><video src={step.output_asset.url} controls playsInline preload="metadata" className="max-h-80 w-full rounded-xl bg-black" /></div>}</div>
            {step.output_asset?.url && <div className="flex flex-wrap gap-2"><a className="rounded-lg border border-border px-3 py-2 text-sm" href={`${step.output_asset.url}&download=1`} target="_blank" rel="noreferrer">Скачать оригинал</a><Button variant="outline" size="sm" disabled={blocked} onClick={() => void action('edit-result', async () => { const output = step.output_asset!; await newWork({ ...freshPlan(), source_asset_id: output.id }, output) })}>Редактировать результат</Button><Button size="sm" variant="ghost" disabled={blocked} onClick={() => void action('redeliver', () => runAction('redeliver', step.id))}>Отправить ещё раз</Button></div>}
            {step.delivery_status && <p className="text-xs text-muted-foreground">Telegram: {statusLabels[step.delivery_status] || step.delivery_status}. Файл доступен в этой работе независимо от чата.</p>}
            {step.status === 'awaiting_confirmation' && <Button disabled={blocked} onClick={() => void action('continue', () => runAction('continue', step.id))}>Продолжить этот шаг</Button>}
          </article>)}
        </div>}
      </div>}
    </>}
  </section>
}
