import '@testing-library/jest-dom'
import { act, render, screen } from '@testing-library/react'
import { DeferredVideoPreview } from '../deferred-video-preview'

let onIntersection: IntersectionObserverCallback | null = null
const observe = jest.fn()
const disconnect = jest.fn()
const originalObserver = global.IntersectionObserver

beforeEach(() => {
  onIntersection = null
  observe.mockClear()
  disconnect.mockClear()
  global.IntersectionObserver = class {
    constructor(callback: IntersectionObserverCallback) {
      onIntersection = callback
    }
    observe = observe
    disconnect = disconnect
    unobserve = jest.fn()
    takeRecords = () => []
    root = null
    rootMargin = ''
    thresholds = []
  } as unknown as typeof IntersectionObserver
})

afterAll(() => {
  global.IntersectionObserver = originalObserver
})

test('offscreen trend video does not request S3 video until visible', () => {
  render(<DeferredVideoPreview data-testid="trend-video" src="https://cdn.example.test/preview.mp4" poster="/preview.jpg" muted autoPlay loop playsInline />)
  const video = screen.getByTestId('trend-video')
  expect(video).not.toHaveAttribute('src')
  expect(video).toHaveAttribute('poster', '/preview.jpg')
  expect(video).toHaveAttribute('preload', 'none')
  expect(observe).toHaveBeenCalledWith(video)

  act(() => onIntersection?.([{ isIntersecting: true }] as IntersectionObserverEntry[], {} as IntersectionObserver))
  expect(video).toHaveAttribute('src', 'https://cdn.example.test/preview.mp4')
  expect(video).toHaveAttribute('preload', 'metadata')
  expect(video).toHaveProperty('autoplay', true)

  act(() => onIntersection?.([{ isIntersecting: false }] as IntersectionObserverEntry[], {} as IntersectionObserver))
  expect(video).not.toHaveAttribute('src')
  expect(video).toHaveAttribute('preload', 'none')
})

test('video remains functional in older WebViews without IntersectionObserver', () => {
  global.IntersectionObserver = undefined as unknown as typeof IntersectionObserver
  render(<DeferredVideoPreview data-testid="fallback-video" src="https://cdn.example.test/preview.mp4" />)
  expect(screen.getByTestId('fallback-video')).toHaveAttribute('src', 'https://cdn.example.test/preview.mp4')
})

test('feed preview remains paused when visible, unlike autoplay trend previews', () => {
  render(<DeferredVideoPreview data-testid="feed-video" src="https://cdn.example.test/feed.mp4" muted playsInline />)
  const video = screen.getByTestId('feed-video')
  act(() => onIntersection?.([{ isIntersecting: true }] as IntersectionObserverEntry[], {} as IntersectionObserver))
  expect(video).toHaveAttribute('src', 'https://cdn.example.test/feed.mp4')
  expect(video).toHaveProperty('autoplay', false)
})
