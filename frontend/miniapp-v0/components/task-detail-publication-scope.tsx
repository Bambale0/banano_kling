'use client'

import { useEffect, useRef, useState } from 'react'
import { Globe2, Loader2, Lock, UserRound, X } from 'lucide-react'
import { toast } from 'sonner'

import { useApp } from '@/lib/app-context'
import {
  getApiBasePath,
  getInitData,
  getStartParamFallback,
} from '@/lib/api'
import { Button } from '@/components/ui/button'
import { TaskDetailPanel as LegacyTaskDetailPanel } from './task-detail-panel'

type PublicationScope = 'private' | 'profile' | 'feed'

type ScopedTask = {
  task_id: string
  is_public_feed?: boolean
  is_profile_visible?: boolean
  publication_scope?: PublicationScope
  feed_prompt_visible?: boolean
  feed_references_visible?: boolean
  feed_blurred?: boolean
}

function getScope(task: ScopedTask | null | undefined): PublicationScope {
  if (!task) return 'private'
  if (task.is_public_feed || task.publication_scope === 'feed') return 'feed'
  if (task.is_profile_visible || task.publication_scope === 'profile') return 'profile'
  return 'private'
}

async function setPublicationScope(
  task: ScopedTask,
  scope: PublicationScope,
): Promise<void> {
  const initData = getInitData()
  if (!initData) {
    throw new Error('Откройте mini app из Telegram и попробуйте снова.')
  }

  const response = await fetch(`${getApiBasePath()}/generations/share`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    credentials: 'same-origin',
    cache: 'no-store',
    body: JSON.stringify({
      init_data: initData,
      start_param_fallback: getStartParamFallback(),
      task_id: task.task_id,
      publication_scope: scope,
      prompt_visible: Boolean(task.feed_prompt_visible),
      references_visible: Boolean(task.feed_references_visible),
      feed_blurred: Boolean(task.feed_blurred),
    }),
  })

  const payload = await response.json().catch(() => null) as
    | { ok?: boolean; error?: string }
    | null
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.error || 'Не удалось изменить публикацию')
  }
}

export function TaskDetailPanel() {
  const { taskDetail, updateTask } = useApp()
  const [chooserOpen, setChooserOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const interceptedButton = useRef<HTMLButtonElement | null>(null)
  const bypassNextClick = useRef(false)

  const scopedTask = taskDetail as (typeof taskDetail & ScopedTask) | null
  const currentScope = getScope(scopedTask)

  useEffect(() => {
    if (typeof document === 'undefined') return

    const interceptLegacyPublication = (event: MouseEvent) => {
      const button = (event.target as HTMLElement | null)?.closest('button') as HTMLButtonElement | null
      if (!button) return
      const label = String(button.textContent || '').replace(/\s+/g, ' ').trim()
      const isPublicationAction = button.dataset.publicationAction === 'scope'
      if (!isPublicationAction &&
        label !== 'Опубликовать' &&
        label !== 'Убрать публикацию' &&
        label !== 'В ленту' &&
        label !== 'Убрать из ленты'
      ) return

      if (bypassNextClick.current) {
        bypassNextClick.current = false
        return
      }

      event.preventDefault()
      event.stopPropagation()
      event.stopImmediatePropagation()
      interceptedButton.current = button
      setChooserOpen(true)
    }

    document.addEventListener('click', interceptLegacyPublication, true)
    return () => document.removeEventListener('click', interceptLegacyPublication, true)
  }, [])

  useEffect(() => {
    setChooserOpen(false)
    interceptedButton.current = null
  }, [taskDetail?.task_id])

  const notifyChanged = () => {
    if (typeof window === 'undefined') return
    window.dispatchEvent(new CustomEvent('banano:feed-changed'))
  }

  const publishToFeed = () => {
    const button = interceptedButton.current
    setChooserOpen(false)
    if (!button) return
    bypassNextClick.current = true
    window.setTimeout(() => button.click(), 0)
  }

  const applyScope = async (scope: Exclude<PublicationScope, 'feed'>) => {
    if (!scopedTask || busy) return

    const target = scope === 'profile' ? 'только в ваш профиль' : 'приватный режим'
    if (
      scope === 'profile' &&
      typeof window !== 'undefined' &&
      !window.confirm(
        `Публикация ${target}\n\n` +
          'Работа будет видна в вашем профиле, но не появится в общей ленте. ' +
          'Подтвердите, что у вас есть права или согласие на исходники и результат.',
      )
    ) {
      return
    }

    setBusy(true)
    try {
      await setPublicationScope(scopedTask, scope)
      updateTask(
        scopedTask.task_id,
        {
          is_public_feed: false,
          is_profile_visible: scope === 'profile',
          publication_scope: scope,
        } as never,
      )
      notifyChanged()
      setChooserOpen(false)
      toast.success(
        scope === 'profile'
          ? 'Опубликовано только в профиле'
          : 'Публикация скрыта',
      )
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось изменить публикацию')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <LegacyTaskDetailPanel />

      {chooserOpen && scopedTask ? (
        <div className="fixed inset-0 z-[70] flex items-end justify-center bg-background/85 p-3 backdrop-blur-sm sm:items-center">
          <div className="w-full max-w-md rounded-3xl border border-border/60 bg-card p-4 shadow-2xl">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <p className="text-lg font-semibold text-foreground">Куда опубликовать?</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  В профиле работа останется доступной по вашей странице, но не попадёт в общую ленту.
                </p>
              </div>
              <button
                type="button"
                aria-label="Закрыть"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground"
                onClick={() => setChooserOpen(false)}
                disabled={busy}
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-2">
              {currentScope !== 'feed' ? (
                <Button
                  type="button"
                  className="h-auto w-full justify-start gap-3 py-3"
                  onClick={publishToFeed}
                  disabled={busy}
                >
                  <Globe2 className="h-5 w-5" />
                  <span className="text-left">
                    <span className="block font-semibold">В общую ленту</span>
                    <span className="block text-xs opacity-80">Появится в ленте и в вашем профиле</span>
                  </span>
                </Button>
              ) : null}

              {currentScope !== 'profile' ? (
                <Button
                  type="button"
                  variant="secondary"
                  className="h-auto w-full justify-start gap-3 py-3"
                  onClick={() => applyScope('profile')}
                  disabled={busy}
                >
                  {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <UserRound className="h-5 w-5" />}
                  <span className="text-left">
                    <span className="block font-semibold">Только в мой профиль</span>
                    <span className="block text-xs text-muted-foreground">В общей ленте показываться не будет</span>
                  </span>
                </Button>
              ) : null}

              {currentScope !== 'private' ? (
                <Button
                  type="button"
                  variant="outline"
                  className="h-auto w-full justify-start gap-3 py-3"
                  onClick={() => applyScope('private')}
                  disabled={busy}
                >
                  {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Lock className="h-5 w-5" />}
                  <span className="text-left">
                    <span className="block font-semibold">Не публиковать</span>
                    <span className="block text-xs text-muted-foreground">Скрыть и из ленты, и из профиля</span>
                  </span>
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  )
}
