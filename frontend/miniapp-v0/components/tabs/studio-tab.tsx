'use client'

import { useApp } from '@/lib/app-context'
import { QuickActionGrid } from '../quick-action-grid'

export function StudioTab() {
  const { setActiveTab, openBalance, openWorkspace } = useApp()

  return (
    <div className="space-y-5 px-3 sm:px-4 lg:space-y-6 lg:px-6">
      <section>
        <div className="mb-3">
          <h1 className="font-serif text-2xl font-semibold tracking-[0.04em] text-foreground lg:text-xl">
            Студия
          </h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Выберите, что хотите создать. Готовые работы остаются в чате с ботом.
          </p>
        </div>
        <QuickActionGrid
          onPhotoClick={() => setActiveTab(1)}
          onVideoClick={() => setActiveTab(2)}
          onMotionClick={() => setActiveTab(3)}
          onBalanceClick={openBalance}
          onAssistantClick={() => openWorkspace('assistant')}
        />
      </section>
    </div>
  )
}
