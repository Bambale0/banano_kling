'use client'

import dynamic from 'next/dynamic'
import { useEffect } from 'react'
import { useApp } from '@/lib/app-context'
import { AnimatePresence, motion } from 'framer-motion'

const StudioTab = dynamic(() => import('./tabs/studio-tab').then((module) => module.StudioTab))
const PhotoTab = dynamic(() => import('./tabs/photo-tab').then((module) => module.PhotoTab))
const VideoTab = dynamic(() => import('./tabs/video-tab').then((module) => module.VideoTab))
const MotionTab = dynamic(() => import('./tabs/motion-tab').then((module) => module.MotionTab))
const FeedTab = dynamic(() => import('./tabs/feed-tab').then((module) => module.FeedTab))
const TrendsTab = dynamic(() => import('./tabs/trends-tab').then((module) => module.TrendsTab))
const ServicesTab = dynamic(() => import('./tabs/services-tab').then((module) => module.ServicesTab))
const ProfileTab = dynamic(() => import('./tabs/profile-tab').then((module) => module.ProfileTab))

const tabComponents = [StudioTab, PhotoTab, VideoTab, MotionTab, FeedTab, TrendsTab, ServicesTab, ProfileTab]

export function TabContent() {
  const { activeTab } = useApp()
  const ActiveComponent = tabComponents[activeTab] || StudioTab

  useEffect(() => {
    const prefetchTimer = window.setTimeout(() => {
      void import('./tabs/feed-tab')
    }, 800)
    return () => window.clearTimeout(prefetchTimer)
  }, [])

  return (
    <div className="relative">
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={false}
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
