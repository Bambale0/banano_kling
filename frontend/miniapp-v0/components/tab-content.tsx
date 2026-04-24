'use client'

import { useApp } from '@/lib/app-context'
import { StudioTab } from './tabs/studio-tab'
import { PhotoTab } from './tabs/photo-tab'
import { VideoTab } from './tabs/video-tab'
import { ServicesTab } from './tabs/services-tab'
import { AnimatePresence, motion } from 'framer-motion'

const tabComponents = [StudioTab, PhotoTab, VideoTab, ServicesTab]

export function TabContent() {
  const { activeTab } = useApp()
  const ActiveComponent = tabComponents[activeTab]

  return (
    <div className="relative">
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ 
            duration: 0.25, 
            ease: [0.25, 0.46, 0.45, 0.94] 
          }}
        >
          <ActiveComponent />
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
