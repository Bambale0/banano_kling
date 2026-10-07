'use client'

import dynamic from 'next/dynamic'
import { type ReactNode, useEffect } from 'react'
import { ThemeProvider } from '@/components/theme-provider'
import { AppProvider, useApp } from '@/lib/app-context'
import { getStartParamFallback } from '@/lib/api'
import { genjutsuRecipeStartParam, parseMiniAppStartParam } from '@/lib/start-params'
import { HeroHeader } from './hero-header'
import { TabNav } from './tab-nav'
import { Toaster } from '@/components/ui/sonner'
import { ClientErrorBoundary } from './client-error-boundary'
import { MiniAppLoader } from './mini-app-loader'
import { TelegramOpenGate } from './telegram-open-gate'
import { PartnerApprovalSheet } from './partner-approval-sheet'
import { GenjutsuEntry } from './genjutsu-entry'
import { BotWriteAccessGate } from './bot-write-access-gate'

const TaskDetailPanel = dynamic(() =>
  import('./task-detail-panel').then((module) => module.TaskDetailPanel),
)
const BalanceSheet = dynamic(() =>
  import('./balance-sheet').then((module) => module.BalanceSheet),
)
const WorkspaceSheet = dynamic(() =>
  import('./workspace-sheet').then((module) => module.WorkspaceSheet),
)

interface MiniAppShellProps {
  children: ReactNode
}


function MiniAppBody({ children }: MiniAppShellProps) {
  const { state, activeWorkspace, trendToRun, setActiveTab, refreshTelegramChatAccess } = useApp()
  const isBootstrapping = state.isLoading
  const isLocked = state.mode === 'locked'

  useEffect(() => {
    if (typeof window === 'undefined' || state.mode !== 'live') return

    const openDefaultTrends = () => {
      const start = getStartParamFallback()
      const rawStartParam = genjutsuRecipeStartParam(start, window.location.search) || start
      const target = rawStartParam ? parseMiniAppStartParam(rawStartParam) : null
      if (target) return
      setActiveTab(5)
    }

    openDefaultTrends()
    // Returning from the bot must preserve the active form and its references.
  }, [setActiveTab, state.mode])

  return (
    <div className="min-h-screen overflow-x-hidden bg-background flex flex-col">
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute inset-0 bg-gradient-to-b from-gold/[0.03] via-transparent to-cyan/[0.02]" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[400px] bg-gold/[0.05] blur-[120px] rounded-full" />
      </div>

      {isBootstrapping ? (
        <MiniAppLoader />
      ) : isLocked ? (
        <TelegramOpenGate />
      ) : (
        <>
          <div className="relative flex flex-col min-h-screen safe-top min-w-0 overflow-x-hidden">
            <HeroHeader />
          {/* A deep-linked trend owns the active Radix modal. Delivery is optional,
              so defer its offer instead of blocking the trend or fighting its focus trap. */}
          <BotWriteAccessGate
            required={state.user.telegramBotStartRequired && !trendToRun}
            botUsername={state.user.botUsername}
            onRefresh={refreshTelegramChatAccess}
          />
            <main className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden pb-[calc(6rem+env(safe-area-inset-bottom))]">
              <div className="mx-auto w-full max-w-[1180px]">
                {state.error && <p role="alert" className="mx-4 mt-4 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{state.error}</p>}
                {children}
              </div>
            </main>
            <TabNav />
          </div>

          <TaskDetailPanel />
          <GenjutsuEntry />
          <BalanceSheet />
          {activeWorkspace === 'partners' ? <PartnerApprovalSheet /> : <WorkspaceSheet />}
        </>
      )}
      <Toaster richColors position="top-center" />
    </div>
  )
}

export function MiniAppShell({ children }: MiniAppShellProps) {
  useEffect(() => {
    if (typeof window === 'undefined') return
    const webApp = window.Telegram?.WebApp
    webApp?.ready?.()
    webApp?.expand?.()
  }, [])

  return (
    <ThemeProvider attribute="class" forcedTheme="dark" enableSystem={false}>
      <ClientErrorBoundary>
        <AppProvider>
          <MiniAppBody>{children}</MiniAppBody>
        </AppProvider>
      </ClientErrorBoundary>
    </ThemeProvider>
  )
}
