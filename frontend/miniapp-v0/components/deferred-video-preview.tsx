'use client'

import { useEffect, useRef, useState, type ComponentProps } from 'react'

/**
 * Large trend/feed grids must not eagerly download dozens of S3 MP4 assets.
 * Only attach src for a card near the viewport; keep its lightweight poster
 * available immediately and preserve the native video player behavior.
 */
export function DeferredVideoPreview({ src, autoPlay = false, ...props }: ComponentProps<'video'>) {
  const ref = useRef<HTMLVideoElement | null>(null)
  const [nearViewport, setNearViewport] = useState(false)

  useEffect(() => {
    const element = ref.current
    if (!element || !src) return

    if (typeof IntersectionObserver === 'undefined') {
      // Old WebViews without the observer still retain a functional preview.
      setNearViewport(true)
      return
    }

    const observer = new IntersectionObserver(
      (entries) => setNearViewport(Boolean(entries[0]?.isIntersecting)),
      { rootMargin: '180px 0px', threshold: 0.01 }
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [src])

  return (
    <video
      {...props}
      ref={ref}
      src={nearViewport ? src : undefined}
      preload={nearViewport ? 'metadata' : 'none'}
      autoPlay={nearViewport && autoPlay}
    />
  )
}
