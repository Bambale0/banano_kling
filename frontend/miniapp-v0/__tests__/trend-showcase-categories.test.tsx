import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { TrendShowcase } from '@/components/trend-showcase'
import { TrendCategoryManager } from '@/components/trend-category-manager'
import type { ShowcaseCategory, ShowcaseTrend } from '@/lib/trend-catalog-api'
import { fetchTrendCategory, adminShowcaseAction } from '@/lib/trend-catalog-api'

jest.mock('@/lib/trend-catalog-api', () => ({
  fetchTrendCategory: jest.fn(),
  adminShowcaseAction: jest.fn(),
}))

const categoryFetch = fetchTrendCategory as jest.MockedFunction<typeof fetchTrendCategory>
const adminAction = adminShowcaseAction as jest.Mock

const makeCard = (id: number, title: string, kind: 'image' | 'video' = 'image'): ShowcaseTrend => ({
  id, title, description: 'Публичное описание',
  category: kind === 'video' ? 'video' : 'photo',
  prompt_text: '', tags: ['trend'],
  model: null, likes: 0, uses_count: 0, author_id: 1,
  status: 'approved',
  preview_url: kind === 'video' ? '/uploads/example.mp4' : '/uploads/example.jpg',
  generation_settings: { kind, preview_type: kind },
} as ShowcaseTrend)

const image = makeCard(21, 'Свечи в торте')
const video = { ...makeCard(22, 'Видео с эффектами', 'video'), badge: 'new' as const }
const catalog: ShowcaseCategory[] = [{
  id: 7, title: 'Видео на День рождения', emoji: '🧁',
  sort_order: 0, is_visible: true, revision: 2, total: 3,
  items: [image, video],
}]

beforeEach(() => {
  jest.clearAllMocks()
  categoryFetch.mockImplementation(async (_id, page) => ({
    category: catalog[0],
    items: page === 1 ? [image, video] : [makeCard(23, 'Третий тренд')],
    total: 3, page, has_more: page === 1,
  }))
})

test('live catalog displays categories, new badge and opens existing repeat flow', () => {
  const onRepeat = jest.fn()
  const onShare = jest.fn()
  render(<TrendShowcase categories={catalog} onRepeat={onRepeat} onShare={onShare} />)
  expect(screen.getByText('🧁 Видео на День рождения')).toBeInTheDocument()
  expect(screen.getByText('Новинка')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Все тренды категории Видео на День рождения' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Открыть тренд Свечи в торте' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByText('Свечи в торте')).toBeInTheDocument()
  expect(within(dialog).getByText('Публичное описание')).toBeInTheDocument()
  fireEvent.click(within(dialog).getByRole('button', { name: /Повторить/ }))
  expect(onRepeat).toHaveBeenCalledWith(image)
  expect(onShare).not.toHaveBeenCalled()
})

test('all opens category page and loads additional cards without changing prompt ids', async () => {
  render(<TrendShowcase categories={catalog} onRepeat={jest.fn()} onShare={jest.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Все тренды категории Видео на День рождения' }))
  await waitFor(() => expect(categoryFetch).toHaveBeenCalledWith(7, 1, 24))
  fireEvent.click(await screen.findByRole('button', { name: 'Показать ещё' }))
  await waitFor(() => expect(categoryFetch).toHaveBeenCalledWith(7, 2, 24))
  expect(await screen.findByRole('button', { name: 'Открыть тренд Третий тренд' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'К категориям' }))
  expect(screen.getByRole('button', { name: 'Все тренды категории Видео на День рождения' })).toBeInTheDocument()
})

test('hidden categories are not rendered to users', () => {
  render(<TrendShowcase categories={[{ ...catalog[0], is_visible: false }]} onRepeat={jest.fn()} onShare={jest.fn()} />)
  expect(screen.queryByRole('button', { name: 'Открыть тренд Свечи в торте' })).not.toBeInTheDocument()
  expect(screen.getByText('Трендов пока нет')).toBeInTheDocument()
})

test('category editor creates folder and saves order via revisions', async () => {
  adminAction.mockResolvedValue({ id: 10, revision: 1 })
  categoryFetch.mockResolvedValue({ category: catalog[0], items: [image, video], page: 1, total: 2, has_more: false })
  const onRefresh = jest.fn().mockResolvedValue(undefined)
  render(<TrendCategoryManager
    open={true}
    onOpenChange={jest.fn()}
    categories={[catalog[0], { ...catalog[0], id: 8, title: 'Reels', emoji: '🎵', revision: 1, sort_order: 1 }]}
    onRefresh={onRefresh}
  />)
  fireEvent.change(screen.getByRole('textbox', { name: 'Название категории' }), { target: { value: 'Новая папка' } })
  fireEvent.click(screen.getByRole('button', { name: 'Создать' }))
  await waitFor(() => expect(adminAction).toHaveBeenCalledWith(expect.objectContaining({
    op: 'create', title: 'Новая папка',
  })))
  await waitFor(() => expect(onRefresh).toHaveBeenCalled())
  fireEvent.click(screen.getByRole('button', { name: 'Категорию Reels вверх' }))
  await waitFor(() => expect(adminAction).toHaveBeenCalledWith(expect.objectContaining({
    op: 'reorder',
    categories: [{ id: 8, revision: 1 }, { id: 7, revision: 2 }],
  })))
})

test('category editor allows adding and sorting existing published trend', async () => {
  adminAction.mockImplementation(async (value) => value.op === 'search_trends'
    ? { items: [makeCard(99, 'Добавляемый ролик')], has_more: false, total: 1, page: 1 }
    : { revision: 3 })
  categoryFetch.mockResolvedValue({ category: catalog[0], items: [image, video], page: 1, total: 2, has_more: false })
  render(<TrendCategoryManager open={true} onOpenChange={jest.fn()} categories={catalog} onRefresh={jest.fn().mockResolvedValue(undefined)} />)
  fireEvent.click(screen.getByRole('button', { name: /^🧁 Видео на День рождения/ }))
  await screen.findByText('Добавляемый ролик')
  fireEvent.click(screen.getByRole('button', { name: /Добавить/ }))
  await waitFor(() => expect(adminAction).toHaveBeenCalledWith({
    op: 'set_items', category_id: 7, revision: 2, trend_ids: [21, 22, 99],
  }))
})
