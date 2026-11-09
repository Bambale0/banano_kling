'use client'

import { useApp } from '@/lib/app-context'
import { cn } from '@/lib/utils'
import { ASTRO_TAB_ID, isAstroVisible } from '@/lib/astro-access'
import { LayoutDashboard, Image, Video, Sparkles, Grid3X3, Images, Flame, UserRound } from 'lucide-react'

const tabs = [
  { id: 0, label: 'Студия', icon: LayoutDashboard },
  { id: 5, label: 'Тренды', icon: Flame },
  { id: 1, label: 'Фото', icon: Image },
  { id: 2, label: 'Видео', icon: Video },
  { id: 4, label: 'Лента', icon: Images },
  { id: 6, label: 'Сервисы', icon: Grid3X3 },
  { id: 7, label: 'Профиль', icon: UserRound },
]

export function TabNav() {
  const { activeTab, setActiveTab, state } = useApp()
  const previewAllowed = isAstroVisible(state)
  // Keep Motion in the original navigation slot for ordinary users.
  const visibleTabs = [
    ...tabs.slice(0, 4),
    previewAllowed
      ? { id: ASTRO_TAB_ID, label: 'Астро', icon: Sparkles }
      : { id: 3, label: 'Motion', icon: Sparkles },
    ...tabs.slice(4),
  ]

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 px-0 sm:px-3 lg:px-4">
      <div className="mx-auto w-full max-w-[900px]">
        <div className="glass-strong border-t border-border/50 safe-bottom sm:rounded-2xl sm:border">
          <div className="flex items-stretch justify-around px-2 py-1 lg:px-3 lg:py-1.5">
            {visibleTabs.map((tab) => {
              const isActive = activeTab === tab.id
              const astroSelected = isActive && tab.id === ASTRO_TAB_ID
              const Icon = tab.icon

              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    "relative flex flex-col items-center justify-center",
                    "flex-1 py-2 px-0.5 rounded-xl lg:py-1.5",
                    "transition-all duration-300 ease-out",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    astroSelected && "rounded-[28px] bg-[#2b2319]/80 shadow-[inset_0_0_18px_rgba(234,168,62,0.12)]",
                    isActive 
                      ? "text-gold" 
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {isActive && (
                    <span 
                      className="absolute inset-x-2 top-0 h-0.5 rounded-full bg-gold"
                      style={{
                        animation: 'fadeSlideIn 0.3s ease-out',
                      }}
                    />
                  )}
                  
                  <span className={cn(
                    "transition-transform duration-300",
                    isActive ? "scale-110" : "scale-100"
                  )}>
                    <Icon className={cn("w-5 h-5", astroSelected && "h-8 w-8 drop-shadow-[0_0_8px_rgba(249,183,70,0.65)]")} strokeWidth={isActive ? 2.5 : 2} />
                  </span>
                  
                  <span className={cn(
                    "text-[9px] mt-1 font-medium",
                    astroSelected && "text-[11px] font-semibold",
                    "transition-all duration-300",
                    isActive ? "opacity-100" : "opacity-70"
                  )}>
                    {tab.label}
                  </span>

                  {isActive && (
                    <span className={cn("absolute inset-0 rounded-xl bg-gold/5 pointer-events-none", astroSelected && "rounded-[28px] bg-gold/0")} />
                  )}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      <style jsx>{`
        @keyframes fadeSlideIn {
          from {
            opacity: 0;
            transform: scaleX(0);
          }
          to {
            opacity: 1;
            transform: scaleX(1);
          }
        }
      `}</style>
    </nav>
  )
}
