'use client'

/**
 * A safe browser projection of the SAME native NEUROMIX model registry and
 * owner-scoped generation history. No Telegram ID, legacy wallet or paid
 * provider adapter is constructed in the frontend.
 *
 * This component shares the Mini App bundle and canonical /mini-app/ URL.
 * Legacy Telegram launches continue to mount MiniAppShell unmodified.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, ExternalLink, Image as ImageIcon, LoaderCircle, LogOut, RefreshCw, Video } from 'lucide-react'

type Actor = {
  account_id: string
  ok: true
  auth_channel: 'web'
  telegram_linked: boolean
  wallet_authority: string
}

type Model = {
  id: string
  label?: string
  description?: string
  web_generate_enabled?: boolean
}

type Catalog = {
  ok: true
  image_models: Model[]
  video_models: Model[]
  web_generate_enabled: boolean
}

type Task = {
  task_id: string
  type?: string
  status?: string
  created_at?: string
  prompt_preview?: string
  prompt_hidden?: boolean
  prompt?: string
  result_url?: string | null
  thumbnail_url?: string | null
}

type HistoryPage = {
  ok: true
  scope: 'web_only' | 'legacy_telegram'
  recent_tasks: Task[]
  next_cursor: string | null
  cursor_reset: boolean
}

type TaskDetail = { ok: true; task: Task }

class SessionExpired extends Error {}

async function getWebData<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method: 'GET',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { Accept: 'application/json' },
    signal,
  })
  if (response.status === 401 || response.status === 403) throw new SessionExpired()
  if (!response.ok) throw new Error('request_failed')
  return response.json() as Promise<T>
}

function safeMediaUrl(value?: string | null): string | null {
  if (!value || typeof value !== 'string') return null
  try {
    const parsed = new URL(value, window.location.origin)
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null
    return parsed.href
  } catch {
    return null
  }
}

function TaskPreview({ task }: { task: Task }) {
  const media = safeMediaUrl(task.thumbnail_url || task.result_url)
  const video = task.type === 'video'
  if (!media) {
    return <div className="flex aspect-video items-center justify-center bg-white/[0.06] text-xs text-[#aca9a0]">
      Превью недоступно
    </div>
  }
  if (video) return <video
    src={safeMediaUrl(task.result_url) || undefined}
    poster={safeMediaUrl(task.thumbnail_url) || undefined}
    controls preload="none" playsInline
    className="aspect-video w-full bg-black object-contain"
    aria-label="Видео результата"
  />
  return <img
    src={media} alt="Изображение результата" loading="lazy" decoding="async"
    className="aspect-video w-full bg-black/40 object-cover"
  />
}

export function BrowserAccountWorkspace() {
  const [actor, setActor] = useState<Actor | null>(null)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [history, setHistory] = useState<HistoryPage | null>(null)
  const [detail, setDetail] = useState<Task | null>(null)
  const [stage, setStage] = useState<'loading' | 'ready' | 'login' | 'error'>('loading')
  const [message, setMessage] = useState('')
  const [paging, setPaging] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [checking, setChecking] = useState(false)
  const generation = useRef(0)
  const controllers = useRef(new Set<AbortController>())

  useEffect(() => {
    const epoch = ++generation.current
    const activeControllers = controllers.current
    const controller = new AbortController()
    activeControllers.add(controller)
    const alive = () => !controller.signal.aborted && epoch === generation.current
    const boot = async () => {
      try {
        // Authenticate before any private history request or model fetch.
        const owner = await getWebData<Actor>('/mini-app/api/web-auth/actor', controller.signal)
        if (!alive()) return
        if (owner.auth_channel !== 'web' || !owner.ok) throw new SessionExpired()
        const [models, tasks] = await Promise.all([
          getWebData<Catalog>('/mini-app/api/web-auth/catalog', controller.signal),
          getWebData<HistoryPage>('/mini-app/api/web-auth/history', controller.signal),
        ])
        if (!alive()) return
        setActor(owner)
        setCatalog(models)
        setHistory(tasks)
        setStage('ready')
      } catch (error) {
        if (!alive()) return
        if (error instanceof SessionExpired) {
          setActor(null)
          setCatalog(null)
          setHistory(null)
          setDetail(null)
          setStage('login')
        } else {
          setStage('error')
          setMessage('Не удалось загрузить веб-студию. Проверьте подключение и повторите вход.')
        }
      } finally {
        activeControllers.delete(controller)
      }
    }
    void boot()
    return () => {
      controller.abort()
      activeControllers.delete(controller)
      generation.current += 1
    }
  }, [])

  const expire = useCallback(() => {
    generation.current += 1
    for (const controller of controllers.current) controller.abort()
    controllers.current.clear()
    setActor(null)
    setCatalog(null)
    setHistory(null)
    setDetail(null)
    setStage('login')
    setPaging(false)
    setDetailLoading(false)
    setChecking(false)
  }, [])

  // Recheck the SAME immutable owner when a tab becomes active. Login/logout
  // in another tab changes the shared HTTP-only cookie; never show stale
  // private media while that second-session check is in flight.
  useEffect(() => {
    if (stage !== 'ready' || !actor) return
    let ongoing: AbortController | null = null
    const verify = async () => {
      if (ongoing || document.hidden) return
      const controller = new AbortController()
      ongoing = controller
      controllers.current.add(controller)
      const epoch = generation.current
      setChecking(true)
      try {
        const current = await getWebData<Actor>('/mini-app/api/web-auth/actor', controller.signal)
        if (controller.signal.aborted || epoch !== generation.current) return
        if (current.account_id !== actor.account_id || current.wallet_authority !== actor.wallet_authority) {
          expire()
        }
      } catch {
        if (!controller.signal.aborted && epoch === generation.current) expire()
      } finally {
        controllers.current.delete(controller)
        ongoing = null
        if (epoch === generation.current) setChecking(false)
      }
    }
    const onVisible = () => { if (!document.hidden) void verify() }
    window.addEventListener('focus', onVisible)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.removeEventListener('focus', onVisible)
      document.removeEventListener('visibilitychange', onVisible)
      ongoing?.abort()
    }
  }, [actor, stage, expire])

  const openTask = async (taskId: string) => {
    if (!actor || !taskId || detailLoading) return
    const epoch = generation.current
    const controller = new AbortController()
    controllers.current.add(controller)
    setDetailLoading(true)
    setMessage('')
    try {
      const result = await getWebData<TaskDetail>(
        '/mini-app/api/web-auth/task?task_id=' + encodeURIComponent(taskId), controller.signal,
      )
      if (generation.current !== epoch || controller.signal.aborted) return
      setDetail(result.task)
    } catch (error) {
      if (generation.current !== epoch || controller.signal.aborted) return
      if (error instanceof SessionExpired) expire()
      else setMessage('Не удалось открыть генерацию. Повторите попытку.')
    } finally {
      controllers.current.delete(controller)
      if (generation.current === epoch) setDetailLoading(false)
    }
  }

  const loadMore = async () => {
    const cursor = history?.next_cursor
    if (!actor || !cursor || paging) return
    const epoch = generation.current
    const controller = new AbortController()
    controllers.current.add(controller)
    setPaging(true)
    setMessage('')
    try {
      const page = await getWebData<HistoryPage>(
        '/mini-app/api/web-auth/history?cursor=' + encodeURIComponent(cursor), controller.signal,
      )
      if (epoch !== generation.current || controller.signal.aborted) return
      setHistory(previous => {
        if (!previous || page.cursor_reset) return page
        const ids = new Set(previous.recent_tasks.map(task => task.task_id))
        const added = page.recent_tasks.filter(task => !ids.has(task.task_id))
        return { ...page, recent_tasks: [...previous.recent_tasks, ...added] }
      })
    } catch (error) {
      if (epoch !== generation.current || controller.signal.aborted) return
      if (error instanceof SessionExpired) expire()
      else setMessage('Не удалось загрузить следующую страницу истории.')
    } finally {
      controllers.current.delete(controller)
      if (epoch === generation.current) setPaging(false)
    }
  }

  const logout = async () => {
    if (loggingOut) return
    setLoggingOut(true)
    // Hide private state before the network roundtrip. A failed logout never
    // restores stale media, and delayed GET responses cannot resurrect it.
    expire()
    try {
      const response = await fetch('/mini-app/api/web-auth/logout', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) setMessage('Не удалось подтвердить выход на сервере. Повторите выход.')
    } catch {
      setMessage('Не удалось подтвердить выход на сервере. Повторите выход.')
    } finally {
      setLoggingOut(false)
    }
  }

  if (stage === 'loading' || checking) return <main
    className="flex min-h-svh items-center justify-center gap-3 bg-[#111719] p-6 text-[#efc17c]"
    role="status">
    <LoaderCircle className="size-5 animate-spin" aria-hidden="true" />
    Проверяем веб-аккаунт…
  </main>

  if (stage === 'login' || stage === 'error') return <main
    className="flex min-h-svh flex-col items-center justify-center gap-5 bg-[#111719] p-6 text-center text-[#f2e8d5]">
    <h1 className="text-3xl font-black">NEUROMIX</h1>
    <p role="status" className="max-w-md text-[#bfb8ac]">
      {message || 'Для просмотра своих работ войдите в веб-аккаунт.'}
    </p>
    <a href="/login" className="border border-[#d8ab67] px-6 py-3 font-bold text-[#f3ca86]">
      Войти в NEUROMIX
    </a>
    {loggingOut || message ? <button
      type="button" disabled={loggingOut} onClick={() => void logout()}
      className="text-xs text-[#d5b67c] underline disabled:opacity-50">
      Повторить выход
    </button> : null}
  </main>

  const jobs = history?.recent_tasks ?? []
  return <main className="min-h-svh bg-[#111719] text-[#f2e8d5]">
    <div className="mx-auto w-full max-w-6xl space-y-8 px-4 pb-16 pt-6 sm:px-7">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-[#bd9559]/40 pb-5">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.28em] text-[#eac184]">NEUROMIX / Web</p>
          <h1 className="text-3xl font-black tracking-tight sm:text-4xl">ВАША AI-СТУДИЯ</h1>
          <p className="mt-2 text-sm text-[#aaa9a2]">
            {actor?.telegram_linked ? 'Связанный аккаунт: ваши генерации Telegram доступны здесь.' :
              'Веб-аккаунт. Telegram для входа не нужен.'}
          </p>
        </div>
        <button type="button" onClick={() => void logout()} disabled={loggingOut}
          className="inline-flex min-h-11 items-center gap-2 border border-[#bd9559]/60 px-4 text-sm disabled:opacity-50">
          <LogOut className="size-4" aria-hidden="true" /> Выйти из веб-аккаунта
        </button>
      </header>

      {message ? <p role="alert" className="border border-amber-500/50 p-4 text-sm text-amber-200">{message}</p> : null}

      {!actor?.telegram_linked ? <a href="/login?link=telegram"
        className="inline-flex min-h-11 items-center border border-[#cca36a]/50 px-4 text-sm text-[#f0c888]">
        Связать Telegram (необязательно)
      </a> : null}

      <section aria-label="Каталог моделей" className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="text-xl font-bold">Модели</h2>
          <p className="text-xs text-[#bcb1a2]">Общий каталог с Telegram · цены и генерация пока отключены для веб-сессий</p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[...(catalog?.image_models ?? []), ...(catalog?.video_models ?? [])].map((model, i) => <article
            key={model.id} className="border border-[#b38c55]/35 bg-[#1b2325] p-4">
            <div className="flex items-center gap-2 text-[#e4b26c]">
              {i < (catalog?.image_models?.length ?? 0)
                ? <ImageIcon className="size-4" aria-hidden="true" />
                : <Video className="size-4" aria-hidden="true" />}
              <h3 className="font-semibold">{model.label || model.id}</h3>
            </div>
            {model.description ? <p className="mt-2 line-clamp-2 text-sm text-[#bcb9b1]">{model.description}</p> : null}
          </article>)}
        </div>
      </section>

      <section aria-label="Мои генерации" className="space-y-4">
        <h2 className="text-xl font-bold">Мои генерации</h2>
        {jobs.length === 0 ? <p role="status" className="border border-[#b38c55]/30 p-5 text-sm text-[#b9b4aa]">
          {actor?.telegram_linked ? 'Генераций пока нет.' :
            'Веб-аккаунт готов. Работы Telegram появятся здесь только после добровольной привязки.'}
        </p> : <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {jobs.map(task => <article key={task.task_id} className="overflow-hidden border border-[#b38c55]/30 bg-[#1b2325]">
            <TaskPreview task={task} />
            <div className="space-y-2 p-4">
              <p className="truncate text-sm text-[#d8cdbb]">
                {task.prompt_hidden ? 'Приватный промпт' : (task.prompt_preview || task.task_id)}
              </p>
              <p className="text-xs text-[#b9ae9d]">{task.status || '—'}</p>
              <button type="button" onClick={() => void openTask(task.task_id)}
                disabled={detailLoading}
                className="inline-flex min-h-10 items-center gap-2 border border-[#cca36a]/60 px-3 text-sm text-[#f0c888] disabled:opacity-50">
                <ExternalLink className="size-4" aria-hidden="true" /> Открыть задачу
              </button>
            </div>
          </article>)}
        </div>}
        {history?.next_cursor ? <button type="button" disabled={paging}
          onClick={() => void loadMore()}
          className="inline-flex min-h-11 items-center gap-2 border border-[#cca36a]/60 px-5 text-sm disabled:opacity-50">
          <RefreshCw className={paging ? 'size-4 animate-spin' : 'size-4'} aria-hidden="true" />
          {paging ? 'Загружаем…' : 'Загрузить ещё'}
        </button> : null}
      </section>

      {detail ? <section aria-label="Детали генерации" className="space-y-4 border border-[#cca36a]/50 bg-[#1b2325] p-4 sm:p-6">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-lg font-bold">Детали генерации</h2>
          <button type="button" aria-label="Закрыть детали" onClick={() => setDetail(null)}
            className="border border-[#b38c55]/50 px-3 py-2 text-sm">Закрыть</button>
        </div>
        <p className="break-all font-mono text-xs text-[#e8c07b]">{detail.task_id}</p>
        <p className="text-sm text-[#bcb9b1]">{detail.status}</p>
        {!detail.prompt_hidden && detail.prompt ? <p className="whitespace-pre-wrap break-words text-sm">{detail.prompt}</p> : null}
        <TaskPreview task={detail} />
      </section> : null}

      <footer className="flex flex-wrap items-center gap-3 border-t border-[#b38c55]/30 pt-6 text-xs text-[#b6b0a6]">
        <ArrowLeft className="size-4 shrink-0" aria-hidden="true" />
        {actor?.telegram_linked ? <>
          <span>В привязанной студии доступны генерация и баланс Telegram. Средства не объединяются автоматически.</span>
          <a href="/login" className="inline-flex min-h-10 items-center border border-[#bd9559]/60 px-3 font-semibold text-[#f3ca86]">
            Открыть привязанную студию
          </a>
        </> : <span>
          Платная генерация для независимых веб-аккаунтов пока недоступна: необходим безопасный общий учёт средств.
        </span>}
      </footer>
    </div>
  </main>
}
