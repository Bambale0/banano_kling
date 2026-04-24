'use client'

import { type ReactNode, useEffect } from 'react'
import { ThemeProvider } from '@/components/theme-provider'
import { AppProvider } from '@/lib/app-context'
import { HeroHeader } from './hero-header'
import { TabNav } from './tab-nav'
import { TaskDetailPanel } from './task-detail-panel'
import { BalanceSheet } from './balance-sheet'
import { WorkspaceSheet } from './workspace-sheet'
import { Toaster } from '@/components/ui/sonner'

interface MiniAppShellProps {
  children: ReactNode
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
      <AppProvider>
        <div className="min-h-screen bg-background flex flex-col">
          <div className="fixed inset-0 pointer-events-none">
            <div className="absolute inset-0 bg-gradient-to-b from-gold/[0.03] via-transparent to-cyan/[0.02]" />
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[400px] bg-gold/[0.05] blur-[120px] rounded-full" />
          </div>
          
          <div className="relative flex flex-col min-h-screen safe-top">
            <HeroHeader />
            <main className="flex-1 overflow-auto pb-20">
              {children}
            </main>
            <TabNav />
          </div>
          
          <TaskDetailPanel />
          <BalanceSheet />
          <WorkspaceSheet />
          <Toaster richColors position="top-center" />
        </div>
      </AppProvider>
    </ThemeProvider>
  )
}
