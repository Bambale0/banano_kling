'use client'

import { useApp } from '@/lib/app-context'
import { useEffect, useRef, useState } from 'react'
import { fetchTaskHistory } from '@/lib/api'
import type { Task } from '@/lib/types'
import { TaskCard } from './task-card'
import { History } from 'lucide-react'

function mergeTasks(previous: Task[], current: Task[]): Task[] {
  const tasks = new Map(previous.map(task => [task.task_id, task]))
  for (const task of current) tasks.set(task.task_id, task)
  return Array.from(tasks.values()).sort((a, b) =>
    (Date.parse(b.created_at) - Date.parse(a.created_at) || 0) || (b.feed_id || 0) - (a.feed_id || 0))
}

export function TaskHistoryList() {
  const { state, taskDetail } = useApp()
  const { recentTasks } = state
  const owner = `${state.mode}:${state.user.telegramId ?? ''}`
  const [history, setHistory] = useState<{ owner: string; tasks: Task[]; cursor?: string | null }>({ owner, tasks: recentTasks })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const active = useRef<AbortController | null>(null)
  useEffect(() => {
    setHistory(previous => {
      const tasks = previous.owner === owner ? mergeTasks(previous.tasks, recentTasks) : recentTasks
      const confirmed = taskDetail && tasks.some(task => task.task_id === taskDetail.task_id) ? [taskDetail] : []
      return { ...(previous.owner === owner ? previous : { owner }), tasks: mergeTasks(tasks, confirmed) }
    })
  }, [owner, recentTasks, taskDetail])
  useEffect(() => {
    active.current?.abort(); active.current = null; setLoading(false); setError('')
    return () => { active.current?.abort(); active.current = null }
  }, [owner])
  const ownedHistory = history.owner === owner ? history : { owner, tasks: recentTasks, cursor: undefined }
  const tasks = mergeTasks(ownedHistory.tasks, recentTasks)
  // Bootstrap stays a small polled window; this is a page size, not a history cap.
  const hasMore = state.mode === 'live' && ownedHistory.cursor !== null
    && (ownedHistory.cursor !== undefined || tasks.length >= 8)
  const loadMore = async () => {
    if (active.current || !hasMore) return
    const controller = new AbortController(); active.current = controller
    const cursor = ownedHistory.cursor ?? tasks.at(-1)?.task_id
    setLoading(true); setError('')
    try {
      const page = await fetchTaskHistory(cursor, controller.signal)
      if (active.current !== controller || controller.signal.aborted) return
      setHistory(previous => previous.owner === owner
        ? { ...previous, tasks: mergeTasks(previous.tasks, page.recent_tasks), cursor: page.next_cursor }
        : previous)
    } catch {
      if (active.current === controller && !controller.signal.aborted) setError('Не удалось загрузить историю. Попробуйте ещё раз.')
    } finally {
      if (active.current === controller) { active.current = null; setLoading(false) }
    }
  }

  if (tasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 px-4">
        <div className="w-16 h-16 rounded-2xl bg-secondary/50 flex items-center justify-center mb-4">
          <History className="w-8 h-8 text-muted-foreground/50" />
        </div>
        <h3 className="text-sm font-medium text-foreground mb-1">
          История пуста
        </h3>
        <p className="text-xs text-muted-foreground text-center max-w-[200px]">
          Созданные задачи появятся здесь
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
    <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 lg:gap-3 xl:grid-cols-4">
      {tasks.map((task, index) => (
        <TaskCard 
          key={task.task_id} 
          task={task}
          index={index % 8}
        />
      ))}
    </div>
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    {hasMore ? <button type="button" disabled={loading} onClick={() => void loadMore()}
      className="w-full rounded-xl border border-border px-4 py-3 text-sm disabled:opacity-50">
      {loading ? 'Загружаю…' : 'Загрузить ещё'}
    </button> : null}
    </div>
  )
}
