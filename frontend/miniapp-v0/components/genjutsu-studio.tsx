'use client'
// Private expiring media bypasses external image optimization.

import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  type Asset, type Bootstrap, type Operation, type Plan, type Preset, type Project,
  type Quote, type Recipe, type Run, type Step, freshPlan, freshStep, genjutsuCall, launchKey,
  operationLabels, roleLabels, statusLabels, uploadGenjutsu,
} from '@/lib/genjutsu-api'
import { GenjutsuAdmin } from './genjutsu-admin'

const field = 'w-full rounded-xl border border-border bg-background px-3 py-2 text-sm'
const section = 'rounded-2xl border border-border bg-card/60 p-4 space-y-3'
const label = 'block space-y-1 text-sm text-muted-foreground'
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
  const [trim, setTrim] = useState({ start: '0', end: '5' })
  const [ack, setAck] = useState(false)
  const [compare, setCompare] = useState(false)
  const [recipe, setRecipe] = useState<Recipe | null>(null)
  const [recipeAssets, setRecipeAssets] = useState<Array<Asset | null>>([])
  const [recipeValues, setRecipeValues] = useState<Record<string, string>>({})
  const [recipeFieldLabels, setRecipeFieldLabels] = useState('')
  const [publishedRecipe, setPublishedRecipe] = useState<Recipe | null>(null)
  const current = useRef({ plan, title, project })
  current.current = { plan, title, project }
  const saved = useRef('')
  const pendingSave = useRef<Promise<Project> | null>(null)
  const alive = useRef(true)
  const video = assets.find(a => a.id === plan.source_asset_id)
  const needsPolling = Boolean(run && ((run.state !== 'review' && !terminal.has(run.state)) || run.steps.some(s => ['pending', 'sending'].includes(s.delivery_status || ''))))
  const limit = (key: string, fallback: number) => Number(bootstrap?.limits[key] ?? fallback)

  const refresh = useCallback(async () => {
    const value = await genjutsuCall<Bootstrap>('bootstrap')
    if (alive.current) { setBootstrap(value); setAssets(value.assets) }
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

  function edit(next: Plan) { setPlan(next); setQuote(null); setAck(false); setError('') }
  function patchStep(index: number, patch: Partial<Step>) {
    edit({ ...plan, steps: plan.steps.map((s, i) => i === index ? { ...s, ...patch } : s) })
  }
  function favorite(id: string) {
    const next = favorites.includes(id) ? favorites.filter(v => v !== id) : [...favorites, id]
    setFavorites(next)
    try { localStorage.setItem('genjutsu-favorite-presets', JSON.stringify(next)) } catch { /* Optional preference. */ }
  }
  async function newWork(next = freshPlan()) {
    if (current.current.plan.source_asset_id && bootstrap?.enabled) await saveCurrent()
    current.current = { project: null, title: 'Новая работа', plan: next }
    saved.current = ''; setRecipe(null); setRecipeAssets([]); setRecipeValues({}); setPublishedRecipe(null)
    setProject(null); setTitle('Новая работа'); setPlan(next); setQuote(null); setTab('editor'); setVersions([])
  }
  async function openProject(id: string, revision?: number) {
    if (current.current.plan.source_asset_id && bootstrap?.enabled) await saveCurrent()
    const value = await genjutsuCall<{ project: Project }>('project', { project_id: id, ...(revision ? { revision } : {}) })
    const latest = revision ? await genjutsuCall<{ project: Project }>('project', { project_id: id }) : value
    // Restoring a snapshot creates a new version, never writes over history.
    const restored = { ...value.project, revision: latest.project.revision }
    current.current = { project: restored, title: restored.title, plan: restored.plan }
    saved.current = revision ? '' : JSON.stringify([restored.title, restored.plan])
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
      current.current.plan = next; edit(next)
    }
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
    setQuote(null)
  }

  async function quoteRecipe() {
    if (!recipe || recipeAssets.some(asset => !asset)) return
    const result = await genjutsuCall<{ quote: Quote; recipe: Recipe }>('recipe_quote', {
      recipe_id: recipe.id,
      reference_asset_ids: recipeAssets.map(asset => asset?.id || ''),
      user_values: recipeValues,
    })
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
    })
    setPublishedRecipe(value.recipe)
  }

  async function getQuote() {
    const savedProject = await saveCurrent()
    const result = await genjutsuCall<{ quote: Quote }>('quote', { project_id: savedProject.id, revision: savedProject.revision })
    setQuote(result.quote); setAck(false)
  }
  async function start() {
    if (!quote) return
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

  return <section className="space-y-4" aria-label="Студия Genjutsu">
    <header className="flex items-start justify-between gap-3">
      <div><p className="text-xs uppercase tracking-widest text-gold">Higgsfield</p><h2 className="font-serif text-2xl">Genjutsu</h2><p className="text-sm text-muted-foreground">Движение, замены и стиль — в одной работе</p></div>
      <Button variant="ghost" aria-label="Закрыть студию" disabled={blocked} onClick={() => void action('close', async () => { if (plan.source_asset_id && bootstrap?.enabled) await saveCurrent(); onClose() })}>Закрыть</Button>
    </header>
    <nav className="flex flex-wrap gap-2" aria-label="Разделы Genjutsu">
      <Button variant={tab === 'editor' ? 'default' : 'outline'} onClick={() => setTab('editor')}>Создать</Button>
      <Button variant={tab === 'history' ? 'default' : 'outline'} onClick={() => { setTab('history'); void refresh().catch(cause => setError(message(cause))) }}>Мои работы</Button>
      {bootstrap?.is_admin && <Button variant={tab === 'admin' ? 'default' : 'outline'} onClick={() => setTab('admin')}>Управление</Button>}
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
          {recipe.current_cost !== null && <p className="text-sm">Текущая стоимость рецепта: <strong>{recipe.current_cost} 🍌</strong></p>}
        </div>
        <fieldset className="space-y-3" disabled={!bootstrap.enabled || blocked}>
          {recipe.slots.map((slot, index) => <div key={index} className={section}>
            <label className={label}>{slot.label}<input type="file" accept="image/*" className={field} onChange={e => { const file = e.target.files?.[0]; void action('recipe-upload', () => uploadRecipeReference(file, index)); e.target.value = '' }} /></label>
            <p className="text-xs text-muted-foreground">Роль: {roleLabels[slot.role] || slot.role}</p>
            {recipeAssets[index]?.url && <img src={recipeAssets[index]?.url || undefined} alt={slot.label} className="h-28 w-28 rounded-xl object-cover" />}
          </div>)}
          {recipe.user_fields.map(fieldSpec => <label key={fieldSpec.key} className={label}>{fieldSpec.label}<input className={field} type={fieldSpec.type === 'number' ? 'number' : fieldSpec.type === 'date' ? 'date' : 'text'} maxLength={fieldSpec.max_length || 160} value={recipeValues[fieldSpec.key] || ''} onChange={e => { setRecipeValues(current => ({ ...current, [fieldSpec.key]: e.target.value })); setQuote(null) }} required={fieldSpec.required !== false} /></label>)}
          <Button disabled={blocked || recipeAssets.some(asset => !asset) || recipe.user_fields.some(fieldSpec => fieldSpec.required !== false && !(recipeValues[fieldSpec.key] || '').trim())} onClick={() => void action('recipe-quote', quoteRecipe)}>Рассчитать стоимость</Button>
        </fieldset>
        {quote && <div className="space-y-3 rounded-2xl border border-gold/40 bg-gold/5 p-4">
          <h3 className="font-medium">Подтверждение запуска</h3>
          <p>Резерв: <strong>{bootstrap.is_admin ? '0' : quote.total_credits} бананов</strong>{bootstrap.is_admin && <span className="text-sm text-muted-foreground"> · пользовательский тариф {quote.total_credits}</span>}</p>
          {quote.allocations.map(a => <div key={`${a.variant}:${a.ordinal}`} className="flex justify-between gap-2 text-sm"><span>Вариант {a.variant + 1}, шаг {a.ordinal + 1}: {operationLabels[a.operation]}</span><span>{a.reserved_credits} 🍌</span></div>)}
          {bootstrap.is_admin && <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />Подтверждаю реальный расход в Higgsfield.</label>}
          <Button disabled={blocked || !bootstrap.configured || (bootstrap.is_admin && !ack)} onClick={() => void action('start', start)}>Запустить тренд</Button>
        </div>}
      </div>}
      {tab === 'editor' && !recipe && <>
        <div className="flex flex-wrap gap-2"><Button disabled={blocked} variant="outline" onClick={() => void action('new', () => newWork())}>Новый проект</Button>
          <label className="flex-1"><span className="sr-only">Открыть проект</span><select className={field} disabled={blocked} value={project?.id || ''} onChange={e => e.target.value && void action('open', () => openProject(e.target.value))}><option value="">Черновики и проекты</option>{bootstrap.projects.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</select></label>
        </div>
        <fieldset className="space-y-4" disabled={!bootstrap.enabled || Boolean(busy)}>
          <div className={section}>
            <label className={label}>Название работы<input className={field} value={title} maxLength={120} onChange={e => { setTitle(e.target.value); setQuote(null) }} /></label>
            {project && <p className="text-xs text-muted-foreground">Версия {project.revision} · изменения сохраняются автоматически</p>}
            {versions.length > 1 && <label className={label}>Восстановить версию<select className={field} value="" disabled={blocked} onChange={e => e.target.value && project && void action('restore', () => openProject(project.id, Number(e.target.value)))}><option value="">Выбрать сохранённую версию</option>{versions.map(v => <option key={v.revision} value={v.revision}>{v.revision}: {v.title}</option>)}</select></label>}
          </div>
          <div className={section}>
            <h3 className="font-medium">1. Исходное видео</h3>
            <label className={label}>Загрузить видео<input type="file" accept="video/*" className={field} onChange={e => { const files = e.target.files; void action('upload', () => upload(files, 'video')); e.target.value = '' }} /></label>
            <label className={label}>Видео из библиотеки<select className={field} value={plan.source_asset_id} onChange={e => edit({ ...plan, source_asset_id: e.target.value })}><option value="">Выберите исходник</option>{assets.filter(a => a.kind === 'video').map(a => <option key={a.id} value={a.id}>Видео {a.id.slice(0, 6)} · {((a.duration_ms || 0) / 1000).toFixed(2)} с</option>)}</select></label>
            {video && <><video key={video.url} src={video.url || undefined} controls playsInline preload="metadata" className="max-h-64 w-full rounded-xl bg-black" />
              <p className="text-xs text-muted-foreground">Фактическая длительность: {((video.duration_ms || 0) / 1000).toFixed(3)} с. Выберите нужный фрагмент до расчёта цены.</p>
              <div className="grid grid-cols-2 gap-2"><label className={label}>Начало, секунды<input className={field} type="number" step="0.001" min="0" value={trim.start} onChange={e => setTrim({ ...trim, start: e.target.value })} /></label><label className={label}>Конец, секунды<input className={field} type="number" step="0.001" value={trim.end} onChange={e => setTrim({ ...trim, end: e.target.value })} /></label></div>
              <Button variant="outline" onClick={() => void action('trim', async () => {
                const result = await genjutsuCall<{ asset: Asset }>('trim', { asset_id: video.id, start_ms: Math.round(Number(trim.start) * 1000), end_ms: Math.round(Number(trim.end) * 1000) })
                setAssets(prev => [result.asset, ...prev]); edit({ ...plan, source_asset_id: result.asset.id })
              })}>Подготовить фрагмент</Button>
            </>}
          </div>
          {plan.steps.map((step, index) => {
            const caps = bootstrap.catalog[step.operation]
            const incompatible = step.references.some(ref => !caps.roles.includes(ref.role)) || step.references.length > caps.max_images
            return <div key={index} className={section}>
              <div className="flex items-center justify-between"><h3 className="font-medium">Шаг {index + 1}</h3>{plan.steps.length > 1 && <Button size="sm" variant="ghost" onClick={() => edit({ ...plan, steps: plan.steps.filter((_, i) => i !== index) })}>Убрать шаг</Button>}</div>
              <div className="grid gap-3 sm:grid-cols-2"><label className={label}>Операция шага {index + 1}<select className={field} value={step.operation} onChange={e => patchStep(index, { operation: e.target.value as Operation, preset_id: null })}>{(Object.keys(bootstrap.catalog) as Operation[]).map(op => <option key={op} value={op}>{operationLabels[op]}</option>)}</select></label>
                <label className={label}>Качество шага {index + 1}<select className={field} value={step.resolution} onChange={e => patchStep(index, { resolution: e.target.value })}>{caps.resolutions.map(v => <option key={v}>{v}</option>)}</select></label></div>
              <p className="text-xs text-muted-foreground">{index ? 'Источник — результат предыдущего шага.' : `Видео от ${caps.minimum_video_ms / 1000} до ${caps.maximum_video_ms / 1000} секунд.`} Референсы: {caps.min_images}–{caps.max_images}. У каждого шага своя стоимость.</p>
              {step.operation === 'restyle' && <div className="space-y-2"><label className={label}>Поиск стиля<input className={field} value={presetSearch} onChange={e => setPresetSearch(e.target.value)} /></label>
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={favoritesOnly} onChange={e => setFavoritesOnly(e.target.checked)} />Только избранные стили</label>
                <div className="grid max-h-64 grid-cols-2 gap-2 overflow-auto sm:grid-cols-3">{shownPresets.map(p => <div key={p.id} className={`rounded-xl border p-2 ${step.preset_id === p.id ? 'border-gold' : 'border-border'}`}><button type="button" aria-pressed={step.preset_id === p.id} className="w-full text-left text-xs" onClick={() => patchStep(index, { preset_id: p.id })}><img src={p.preview_url} alt="" loading="lazy" className="mb-1 aspect-video w-full rounded-lg object-cover" />{p.name}</button><button type="button" className="mt-1 text-xs text-gold" onClick={() => favorite(p.id)}>{favorites.includes(p.id) ? 'Убрать из избранного' : 'В избранное'}</button></div>)}</div>
                {!presets.length && <p className="text-sm text-muted-foreground">Каталог стилей пока недоступен.</p>}
                {step.preset_id && !presets.some(p => p.id === step.preset_id) && <p role="alert">Сохранённый стиль не найден. Выберите доступный стиль.</p>}
                <p className="text-xs text-muted-foreground">Без фото стилизуются персонажи исходного видео. Фото здесь используются только как референсы персонажей, не как фон или пресет.</p>
              </div>}
              <label className={label}>Загрузить референсы к шагу {index + 1}<input type="file" multiple accept="image/*" className={field} onChange={e => { const files = e.target.files; void action('references', () => upload(files, 'image', index)); e.target.value = '' }} /></label>
              <label className={label}>Добавить референс к шагу {index + 1}<select className={field} value="" onChange={e => { if (e.target.value) patchStep(index, { references: [...step.references, { asset_id: e.target.value, role: 'character', label: '', binding: 'user' as const }] }) }} disabled={step.references.length >= caps.max_images}><option value="">Из моей библиотеки</option>{assets.filter(a => a.kind === 'image' && !step.references.some(r => r.asset_id === a.id)).map(a => <option key={a.id} value={a.id}>Фото {a.id.slice(0, 8)}</option>)}</select></label>
              {step.references.map((ref, refIndex) => {
                const asset = assets.find(a => a.id === ref.asset_id)
                return <div key={ref.asset_id} className="grid grid-cols-[48px_1fr] gap-2 rounded-xl border border-border p-2">
                  {asset?.url ? <img src={asset.url} alt={`Референс ${refIndex + 1}`} className="h-12 w-12 rounded-lg object-cover" /> : <span className="text-xs">Фото {refIndex + 1}</span>}
                  <div className="space-y-2"><select aria-label={`Роль референса ${refIndex + 1} шага ${index + 1}`} className={field} value={ref.role} onChange={e => patchStep(index, { references: step.references.map((r, i) => i === refIndex ? { ...r, role: e.target.value } : r) })}>{!caps.roles.includes(ref.role) && <option value={ref.role}>{roleLabels[ref.role]} — не поддерживается</option>}{caps.roles.map(r => <option key={r} value={r}>{roleLabels[r] || r}</option>)}</select>
                    {bootstrap.is_admin && <label className={label}>В тренде<select className={field} value={ref.binding || 'user'} onChange={e => patchStep(index, { references: step.references.map((r, i) => i === refIndex ? { ...r, binding: e.target.value as 'user' | 'fixed' } : r) })}><option value="user">Пользователь заменяет</option><option value="fixed">Закреплённый референс</option></select></label>}
                    <input aria-label={`Назначение референса ${refIndex + 1} шага ${index + 1}`} className={field} maxLength={200} placeholder="Например: герой слева; ещё одно фото того же героя" value={ref.label} onChange={e => patchStep(index, { references: step.references.map((r, i) => i === refIndex ? { ...r, label: e.target.value } : r) })} />
                    <div className="flex gap-2"><Button size="sm" variant="outline" disabled={refIndex === 0} onClick={() => { const next = [...step.references]; [next[refIndex - 1], next[refIndex]] = [next[refIndex], next[refIndex - 1]]; patchStep(index, { references: next }) }}>Выше</Button><Button size="sm" variant="ghost" onClick={() => patchStep(index, { references: step.references.filter((_, i) => i !== refIndex) })}>Убрать</Button></div>
                  </div>
                </div>
              })}
              {incompatible && <p role="alert" className="text-sm text-destructive">Референсы сохранены, но не подходят новому режиму. Измените роли или количество перед запуском.</p>}
              <label className={label}>Что изменить — шаг {index + 1}<textarea className={field} rows={3} maxLength={caps.max_prompt_length} value={step.prompt} onChange={e => patchStep(index, { prompt: e.target.value })} /></label>
              <label className={label}>Что сохранить — шаг {index + 1}<textarea className={field} rows={2} maxLength={2000} value={step.preserve} onChange={e => patchStep(index, { preserve: e.target.value })} placeholder="Например: лицо, движение камеры и фон" /></label>
            </div>
          })}
          <Button variant="outline" disabled={plan.steps.length >= limit('max_steps', 1)} onClick={() => edit({ ...plan, steps: [...plan.steps, freshStep()] })}>Добавить следующий шаг</Button>
          <div className={section}>
            <label className={label}>Количество вариантов<input className={field} type="number" min={1} max={limit('max_variants', 1)} value={plan.variants} onChange={e => edit({ ...plan, variants: Number(e.target.value) })} /></label>
            {plan.steps.length > 1 && <label className={label}>Продолжение цепочки<select className={field} value={plan.continuation} onChange={e => edit({ ...plan, continuation: e.target.value as Plan['continuation'] })}><option value="automatic">Автоматически после каждого результата</option><option value="manual">Подтверждать следующий шаг</option></select></label>}
            <p className="text-xs text-muted-foreground">Каждый вариант запускается отдельно. При сбое позднего шага предыдущие результаты сохраняются; возвращается резерв неуспешного и незапущенных шагов.</p>
            <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={blocked || !plan.source_asset_id} onClick={() => void action('save', async () => { await saveCurrent(); await refresh() })}>Сохранить проект</Button><Button disabled={blocked || !plan.source_asset_id} onClick={() => void action('quote', getQuote)}>Рассчитать стоимость</Button></div>
            {bootstrap.is_admin && <div className="mt-3 space-y-2 rounded-xl border border-border p-3"><p className="text-sm font-medium">Рецепт для «Трендов»</p><p className="text-xs text-muted-foreground">Для каждого фото выше выберите «Пользователь заменяет» или «Закреплённый референс». Дополнительные поля укажите названиями через запятую.</p><input className={field} value={recipeFieldLabels} onChange={e => setRecipeFieldLabels(e.target.value)} placeholder="Имя, Возраст, Надпись" /><Button type="button" variant="outline" disabled={blocked || !plan.source_asset_id} onClick={() => void action('publish-recipe', publishRecipe)}>Создать приватный рецепт</Button>{publishedRecipe && <p className="break-all text-xs">Рецепт готов: <strong>{publishedRecipe.id}</strong> · пользовательских фото: {publishedRecipe.slots.length}{publishedRecipe.current_cost !== null ? ` · сейчас ${publishedRecipe.current_cost} 🍌` : ''}</p>}</div>}
          </div>
        </fieldset>
        {quote && <div className="space-y-3 rounded-2xl border border-gold/40 bg-gold/5 p-4">
          <h3 className="font-medium">Подтверждение запуска</h3>
          <p>Резерв: <strong>{bootstrap.is_admin ? '0' : quote.total_credits} бананов</strong>{bootstrap.is_admin && <span className="text-sm text-muted-foreground"> · пользовательский тариф {quote.total_credits}</span>}</p>
          <p className="text-xs text-muted-foreground">Действует до {new Date(quote.expires_ms).toLocaleTimeString()}. Сейчас на балансе {bootstrap.credits}.</p>
          {quote.allocations.map(a => <div key={`${a.variant}:${a.ordinal}`} className="flex justify-between gap-2 text-sm"><span>Вариант {a.variant + 1}, шаг {a.ordinal + 1}: {operationLabels[a.operation]}{a.maximum_reserve ? ' · максимальный резерв' : ''}</span><span>{a.reserved_credits} 🍌</span></div>)}
          {quote.allocations.some(a => a.maximum_reserve) && <p className="text-xs">Стоимость следующих шагов уточняется по фактическому входу. Неиспользованный резерв возвращается автоматически. Больше подтверждённой суммы не списывается.</p>}
          {bootstrap.is_admin && <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)} />Подтверждаю платный запрос к Higgsfield. Бананы администратора не списываются, но провайдер расходует реальные средства.</label>}
          <Button disabled={blocked || !bootstrap.enabled || !bootstrap.configured || (bootstrap.is_admin && !ack)} onClick={() => void action('start', start)}>Запустить</Button>
          <p className="text-xs text-muted-foreground">При потере связи повтор этой кнопки использует тот же запуск, а не создаёт ещё одно списание.</p>
        </div>}
      </>}
      {tab === 'history' && <div className="space-y-4">
        <div className="flex flex-wrap gap-2">{bootstrap.runs.map(item => <Button key={item.id} variant={run?.id === item.id ? 'default' : 'outline'} size="sm" disabled={blocked} onClick={() => void action('run', async () => { setRun((await genjutsuCall<{ run: Run }>('run', { run_id: item.id })).run) })}>{new Date(item.created_ms).toLocaleDateString()} · {statusLabels[item.state] || item.state} · {item.id.slice(0, 6)}</Button>)}</div>
        {!bootstrap.runs.length && !run && <p className={section}>Здесь появятся принятые задачи. Черновики доступны в разделе «Создать».</p>}
        {run && <div className={section}>
          <div className="flex flex-wrap items-center justify-between gap-2"><div><h3>{statusLabels[run.state] || run.state}</h3><p className="break-all text-xs text-muted-foreground">{run.id}</p></div><Button variant="outline" disabled={blocked} onClick={() => void action('refresh-run', async () => { setRun((await genjutsuCall<{ run: Run }>('run', { run_id: run.id })).run) })}>Обновить статус</Button></div>
          <div className="flex flex-wrap gap-2">{!terminal.has(run.state) && <Button variant="outline" disabled={blocked || Boolean(run.cancel_requested)} onClick={() => void action('cancel', () => runAction('cancel'))}>Отменить оставшиеся шаги</Button>}
            {run.plan && <Button variant="outline" disabled={blocked} onClick={() => void action('repeat', () => newWork(run.plan))}>Повторить с настройками</Button>}
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={compare} onChange={e => setCompare(e.target.checked)} />Показать исходник рядом</label></div>
          {run.steps.map(step => <article key={step.id} className="space-y-2 border-t border-border pt-3">
            <h4 className="text-sm font-medium">Вариант {step.variant + 1} · шаг {step.ordinal + 1} · {operationLabels[step.spec.operation]} · {step.spec.resolution}</h4>
            <p className="text-sm">{statusLabels[step.status] || step.status}</p>
            <p className="text-xs text-muted-foreground">Резерв {step.reserved_credits} 🍌 · возврат {step.refunded_credits} 🍌{step.actual_credits !== null ? ` · расчёт ${step.actual_credits} 🍌` : ''}</p>
            {step.error_code && <p className="break-all text-xs text-destructive">Код: {step.error_code}. Результаты остальных шагов не потеряны.</p>}
            <div className={compare ? 'grid gap-2 sm:grid-cols-2' : ''}>{compare && step.source_asset?.url && <div><p className="text-xs">Исходник</p><video src={step.source_asset.url} controls playsInline preload="metadata" className="max-h-80 w-full rounded-xl bg-black" /></div>}{step.output_asset?.url && <div><p className="text-xs">Результат</p><video src={step.output_asset.url} controls playsInline preload="metadata" className="max-h-80 w-full rounded-xl bg-black" /></div>}</div>
            {step.output_asset?.url && <div className="flex flex-wrap gap-2"><a className="rounded-lg border border-border px-3 py-2 text-sm" href={`${step.output_asset.url}&download=1`} target="_blank" rel="noreferrer">Скачать оригинал</a><Button variant="outline" size="sm" disabled={blocked} onClick={() => void action('edit-result', async () => { const output = step.output_asset!; setAssets(prev => [output, ...prev.filter(a => a.id !== output.id)]); await newWork({ ...freshPlan(), source_asset_id: output.id }) })}>Редактировать результат</Button><Button size="sm" variant="ghost" disabled={blocked} onClick={() => void action('redeliver', () => runAction('redeliver', step.id))}>Отправить ещё раз</Button></div>}
            {step.delivery_status && <p className="text-xs text-muted-foreground">Telegram: {statusLabels[step.delivery_status] || step.delivery_status}. Файл доступен в этой работе независимо от чата.</p>}
            {step.status === 'awaiting_confirmation' && <Button disabled={blocked} onClick={() => void action('continue', () => runAction('continue', step.id))}>Продолжить этот шаг</Button>}
          </article>)}
        </div>}
      </div>}
    </>}
  </section>
}
