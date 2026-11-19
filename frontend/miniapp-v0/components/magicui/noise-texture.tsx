'use client'

// Adapted from Magic UI's NoiseTexture (MIT License).
// Copyright (c) Magic UI. See docs/licenses/MAGICUI.md.
import { useId, type ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export interface NoiseTextureProps extends ComponentProps<'svg'> {
  frequency?: number
  octaves?: number
  slope?: number
  noiseOpacity?: number
}

/**
 * Non-animated analog paper grain for the NEUROMIX grunge identity.
 * Pure SVG turbulence: no canvas loop, network calls or extra npm packages.
 */
export function NoiseTexture({
  frequency = 0.48,
  octaves = 3,
  slope = 0.24,
  noiseOpacity = 0.45,
  className,
  ...props
}: NoiseTextureProps) {
  const filterId = useId()

  return (
    <svg
      aria-hidden="true"
      focusable="false"
      xmlns="http://www.w3.org/2000/svg"
      className={cn('pointer-events-none absolute inset-0 size-full select-none', className)}
      {...props}
    >
      <filter id={filterId}>
        <feTurbulence
          type="fractalNoise"
          baseFrequency={frequency}
          numOctaves={octaves}
          stitchTiles="stitch"
        />
        <feColorMatrix type="saturate" values="0" />
        <feComponentTransfer>
          <feFuncR type="linear" slope={slope} />
          <feFuncG type="linear" slope={slope} />
          <feFuncB type="linear" slope={slope} />
        </feComponentTransfer>
      </filter>
      <rect width="100%" height="100%" filter={`url(#${filterId})`} opacity={noiseOpacity} />
    </svg>
  )
}
