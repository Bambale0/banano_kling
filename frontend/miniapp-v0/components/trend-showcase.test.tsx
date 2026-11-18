import '@testing-library/jest-dom'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { TrendShowcase } from './trend-showcase'
import type { ShowcaseCategory, ShowcaseTrend } from '@/lib/trend-catalog-api'

const original = '/uploads/feed/original.mp4'
const videoPoster = '/uploads/trend-previews/catalog/poster.jpg'
const imageOriginal = '/uploads/refs/image/example.png'
const imageThumbnail = '/uploads/trend-previews/catalog/image.jpg'

function trend(id: number, previewUrl: string, posterUrl?: string): ShowcaseTrend {
  return {
    id, title: 'Тестовый тренд ' + id, description: '',
    preview_url: previewUrl,
    preview_poster_url: posterUrl || null,
    category: /\.mp4$/.test(previewUrl) ? 'video' : 'photo',
    generation_settings: { preview_type: /\.mp4$/.test(previewUrl) ? 'video' : 'image' },
    tags: ['trend'], repeat_cost: 0,
  } as unknown as ShowcaseTrend
}

function show(item: ShowcaseTrend) {
  const categories: ShowcaseCategory[] = [{
    id: 1, title: 'Видео и фото', emoji: '', sort_order: 0, revision: 1,
    is_visible: true, total: 1, items: [item],
  }]
  return render(<TrendShowcase categories={categories}
    onRepeat={jest.fn()} onShare={jest.fn()} />)
}

describe('Trend showcase viewport loading', () => {
  it('never attaches a thumbnail URL before the tile enters the viewport', () => {
    const originalObserver = global.IntersectionObserver
    let enterViewport: (() => void) | undefined
    class TestObserver {
      private onChange: IntersectionObserverCallback
      constructor(callback: IntersectionObserverCallback) { this.onChange = callback }
      observe = jest.fn(() => {
        enterViewport = () => this.onChange([{ isIntersecting: true, intersectionRatio: 1 }] as IntersectionObserverEntry[], this as unknown as IntersectionObserver)
      })
      unobserve = jest.fn()
      disconnect = jest.fn()
      takeRecords = jest.fn(() => [])
    }
    Object.defineProperty(global, 'IntersectionObserver', { configurable: true, value: TestObserver })
    try {
      const { container } = show(trend(15, imageOriginal, imageThumbnail))
      const card = screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 15' })
      expect(card.querySelector('img')).toBeNull()
      expect(enterViewport).toBeDefined()
      act(() => { enterViewport?.() })
      expect(card.querySelector('img')?.getAttribute('src')).toContain(imageThumbnail)
      expect(card.querySelector('img')?.getAttribute('loading')).toBe('eager')
      expect(container.querySelector('video')).toBeNull()
    } finally {
      Object.defineProperty(global, 'IntersectionObserver', { configurable: true, value: originalObserver })
    }
  })
})

describe('Trend showcase S3 preview performance', () => {
  // The gallery assertions concern media after the card enters the viewport.
  // Jest's shared IntersectionObserver mock does not emit intersections.
  const originalObserver = global.IntersectionObserver
  beforeEach(() => {
    class VisibleObserver {
      private callback: IntersectionObserverCallback
      constructor(callback: IntersectionObserverCallback) { this.callback = callback }
      observe = jest.fn(() => {
        this.callback([{ isIntersecting: true, intersectionRatio: 1 }] as IntersectionObserverEntry[], this as unknown as IntersectionObserver)
      })
      unobserve = jest.fn()
      disconnect = jest.fn()
      takeRecords = jest.fn(() => [])
    }
    Object.defineProperty(global, 'IntersectionObserver', { configurable: true, value: VisibleObserver })
  })
  afterEach(() => {
    Object.defineProperty(global, 'IntersectionObserver', { configurable: true, value: originalObserver })
  })
  it('does not attach the original full MP4 to the scrolling grid', () => {
    const { container } = show(trend(1, original))
    expect(screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 1' })).toBeInTheDocument()
    expect(container.querySelector('video')).toBeNull()
    // No full video fetch until the user opens the card.
    fireEvent.click(screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 1' }))
    expect(screen.getByRole('dialog').querySelector('video')?.getAttribute('src'))
      .toContain('/uploads/feed/original.mp4#t=0.001')
  })

  it('renders a lightweight video poster without downloading a full MP4', () => {
    const { container } = show(trend(2, original, videoPoster))
    const card = screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 2' })
    expect(card.querySelector('img')?.getAttribute('src')).toContain(videoPoster)
    expect(container.querySelector('video')).toBeNull()
  })

  it('uses tiny image thumbnails in grid but original in full-screen dialog', () => {
    show(trend(3, imageOriginal, imageThumbnail))
    const card = screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 3' })
    expect(card.querySelector('img')?.getAttribute('src')).toContain(imageThumbnail)
    fireEvent.click(card)
    expect(screen.getByRole('dialog').querySelector('img')?.getAttribute('src'))
      .toContain(imageOriginal)
  })

  it('recovers the original image if S3 thumbnail is missing', () => {
    show(trend(4, imageOriginal, imageThumbnail))
    const card = screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 4' })
    const image = card.querySelector('img')!
    fireEvent.error(image)
    expect(card.querySelector('img')?.getAttribute('src')).toContain(imageOriginal)
  })


  it('always uses same-origin poster even if a legacy API includes a signed URL', () => {
    const direct = 'https://s3.example.test/bucket/poster.jpg?X-Amz-Signature=temporary'
    const item = { ...trend(7, original, videoPoster), preview_poster_fast_url: direct }
    const { container } = show(item)
    const card = screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 7' })
    const image = card.querySelector('img')!
    expect(image.getAttribute('src')).toContain(videoPoster)
    expect(image.getAttribute('src')).not.toContain('s3.example.test')
    expect(container.querySelector('video')).toBeNull()
  })

  it('never routes photo thumbnails through external S3 even with fast URL present', () => {
    const direct = 'https://s3.example.test/bucket/image.jpg?X-Amz-Signature=temporary'
    const item = { ...trend(8, imageOriginal, imageThumbnail), preview_poster_fast_url: direct }
    show(item)
    const card = screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 8' })
    expect(card.querySelector('img')?.getAttribute('src')).toContain(imageThumbnail)
    fireEvent.error(card.querySelector('img')!)
    expect(card.querySelector('img')?.getAttribute('src')).toContain(imageOriginal)
  })
})
