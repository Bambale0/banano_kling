'use client'

import dynamic from 'next/dynamic'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { getStartParamFallback } from '@/lib/api'
import { genjutsuCall, openGenjutsu } from '@/lib/genjutsu-api'

const Studio = dynamic(() => import('./genjutsu-studio').then(module => module.GenjutsuStudio), {
  loading: () => <p role="status">Открываем Genjutsu…</p>,
})
type Options = { task_id?: string; run_id?: string; recipe_id?: string }

export function GenjutsuButton({ taskId, compact = false }: { taskId?: string; compact?: boolean }) {
  const [visible, setVisible] = useState(false)
  useEffect(() => {
    let active = true
    void genjutsuCall<{ visible: boolean }>('availability').then(value => { if (active) setVisible(value.visible) }).catch(() => { /* Existing video tools remain unaffected. */ })
    return () => { active = false }
  }, [])
  if (!visible) return null
  return <Button variant="outline" size={compact ? 'sm' : 'default'} className={compact ? '' : 'h-auto min-h-10 w-full whitespace-normal border-gold/30'} onClick={() => openGenjutsu(taskId ? { task_id: taskId } : {})}>
    {taskId ? 'Изменить в Genjutsu' : 'Higgsfield Genjutsu · движение, замены и стиль'}
  </Button>
}

export function GenjutsuEntry() {
  const [options, setOptions] = useState<Options | null>(null)
  const [session, setSession] = useState(0)
  useEffect(() => {
    const show = (event: Event) => {
      const detail = (event as CustomEvent<Options>).detail || {}
      setOptions(detail); setSession(value => value + 1)
    }
    window.addEventListener('genjutsu:open', show)
    const params = new URLSearchParams(window.location.search)
    const start = getStartParamFallback()
    if (params.get('genjutsu') === '1' || start === 'genjutsu' || start.startsWith('genjutsu_recipe_')) {
      const rid = params.get('genjutsu_run')
      const recipe = params.get('genjutsu_recipe') || (start.startsWith('genjutsu_recipe_') ? start.slice(16) : '')
      setOptions({ ...(rid && /^[a-f0-9]{32}$/.test(rid) ? { run_id: rid } : {}),
        ...(recipe && /^[a-f0-9]{32}$/.test(recipe) ? { recipe_id: recipe } : {}) })
    }
    return () => window.removeEventListener('genjutsu:open', show)
  }, [])
  function close() {
    setOptions(null)
    const url = new URL(window.location.href)
    for (const key of ['genjutsu', 'genjutsu_run', 'genjutsu_recipe']) url.searchParams.delete(key)
    window.history.replaceState(window.history.state, '', url.toString())
  }
  return <Dialog open={options !== null} onOpenChange={open => { if (!open) window.dispatchEvent(new Event('genjutsu:request-close')) }}>
    <DialogContent showCloseButton={false} className="max-h-[94dvh] max-w-[min(940px,96vw)] overflow-y-auto p-4 sm:max-w-[min(940px,96vw)] sm:p-6" onPointerDownOutside={event => event.preventDefault()}>
      <DialogTitle className="sr-only">Студия Genjutsu</DialogTitle>
      <DialogDescription className="sr-only">Редактирование видео с помощью Higgsfield. Перед запуском показывается стоимость.</DialogDescription>
      {options && <Studio key={session} initial={options} onClose={close} />}
    </DialogContent>
  </Dialog>
}
