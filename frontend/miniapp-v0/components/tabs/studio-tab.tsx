'use client'

import { useApp } from '@/lib/app-context'
import { QuickActionGrid } from '../quick-action-grid'
import { TaskHistoryList } from '../task-history-list'

export function StudioTab() {
  const { setActiveTab, openBalance, openWorkspace } = useApp()

  return (
    <div className="space-y-5 px-3 sm:px-4">
      {/* Quick Start */}
      <section>
        <div className="mb-3 flex items-end justify-between">
          <div>
            <h1 className="font-serif text-2xl font-semibold text-foreground">Создавайте</h1>
            <p className="mt-0.5 text-xs text-muted-foreground">Фото и видео с нейросетями</p>
          </div>
        </div>
        <QuickActionGrid 
          onPhotoClick={() => setActiveTab(1)}
          onVideoClick={() => setActiveTab(2)}
          onMotionClick={() => setActiveTab(3)}
          onBalanceClick={openBalance}
          onAssistantClick={() => openWorkspace('assistant')}
        />
      </section>

      {/* Recent Tasks */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-serif text-base font-semibold text-foreground">
            Ваши работы
          </h2>
        </div>
        <TaskHistoryList />
      </section>
    </div>
  )
}
