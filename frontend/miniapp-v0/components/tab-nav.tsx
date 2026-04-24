'use client'

import { useApp } from '@/lib/app-context'
import { cn } from '@/lib/utils'
import { LayoutDashboard, Image, Video, Grid3X3 } from 'lucide-react'

const tabs = [
  { id: 0, label: 'Студия', icon: LayoutDashboard },
  { id: 1, label: 'Фото', icon: Image },
  { id: 2, label: 'Видео', icon: Video },
  { id: 3, label: 'Сервисы', icon: Grid3X3 },
]

export function TabNav() {
  const { activeTab, setActiveTab } = useApp()

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50">
      <div className="glass-strong border-t border-border/50 safe-bottom">
        <div className="flex items-stretch justify-around px-2 py-1">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id
            const Icon = tab.icon

            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "relative flex flex-col items-center justify-center",
                  "flex-1 py-2 px-1 rounded-xl",
                  "transition-all duration-300 ease-out",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  isActive 
                    ? "text-gold" 
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {/* Active indicator */}
                {isActive && (
                  <span 
                    className="absolute inset-x-2 top-0 h-0.5 rounded-full bg-gold"
                    style={{
                      animation: 'fadeSlideIn 0.3s ease-out',
                    }}
                  />
                )}
                
                {/* Icon with scale animation */}
                <span className={cn(
                  "transition-transform duration-300",
                  isActive ? "scale-110" : "scale-100"
                )}>
                  <Icon className="w-5 h-5" strokeWidth={isActive ? 2.5 : 2} />
                </span>
                
                {/* Label */}
                <span className={cn(
                  "text-[10px] mt-1 font-medium",
                  "transition-all duration-300",
                  isActive ? "opacity-100" : "opacity-70"
                )}>
                  {tab.label}
                </span>

                {/* Subtle glow for active state */}
                {isActive && (
                  <span className="absolute inset-0 rounded-xl bg-gold/5 pointer-events-none" />
                )}
              </button>
            )
          })}
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
