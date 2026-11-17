import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
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

describe('Trend showcase S3 preview performance', () => {
  it('does not attach the original full MP4 to the scrolling grid', () => {
    const { container } = show(trend(1, original))
    expect(screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 1' })).toBeInTheDocument()
    expect(container.querySelector('video')).toBeNull()
    // No full video fetch until the user opens the card.
    fireEvent.click(screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 1' }))
    expect(container.querySelector('video')).toHaveAttribute('src', original + '#t=0.001')
  })

  it('renders a lightweight video poster without downloading a full MP4', () => {
    const { container } = show(trend(2, original, videoPoster))
    const card = screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 2' })
    expect(card.querySelector('img')).toHaveAttribute('src', videoPoster)
    expect(container.querySelector('video')).toBeNull()
  })

  it('uses tiny image thumbnails in grid but original in full-screen dialog', () => {
    const { container } = show(trend(3, imageOriginal, imageThumbnail))
    const card = screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 3' })
    expect(card.querySelector('img')).toHaveAttribute('src', imageThumbnail)
    fireEvent.click(card)
    expect(container.querySelector('img[src="' + imageOriginal + '"]')).toBeInTheDocument()
  })

  it('recovers the original image if S3 thumbnail is missing', () => {
    show(trend(4, imageOriginal, imageThumbnail))
    const card = screen.getByRole('button', { name: 'Открыть тренд Тестовый тренд 4' })
    const image = card.querySelector('img')!
    fireEvent.error(image)
    expect(card.querySelector('img')).toHaveAttribute('src', imageOriginal)
  })
})
