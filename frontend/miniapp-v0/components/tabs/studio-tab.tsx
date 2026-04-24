'use client'

import { useApp } from '@/lib/app-context'
import { QuickActionGrid } from '../quick-action-grid'
import { TaskHistoryList } from '../task-history-list'

export function StudioTab() {
  const { setActiveTab, openBalance, openWorkspace } = useApp()

  return (
    <div className="px-4 space-y-6">
      {/* Quick Start */}
      <section>
        <h2 className="font-serif text-lg font-semibold text-foreground mb-3">
          Быстрый старт
        </h2>
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
          <h2 className="font-serif text-lg font-semibold text-foreground">
            Последние задачи
          </h2>
        </div>
        <TaskHistoryList />
      </section>
    </div>
  )
}
