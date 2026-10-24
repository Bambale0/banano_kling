import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { TrendShowcase } from '@/components/trend-showcase'
import { TrendCategoryManager } from '@/components/trend-category-manager'
import type { ShowcaseCategory, ShowcaseTrend } from '@/lib/trend-catalog-api'
import { fetchTrendCategory, adminShowcaseAction } from '@/lib/trend-catalog-api'

jest.mock('@/lib/trend-catalog-api', () => ({
  fetchTrendCategory: jest.fn(),
  adminShowcaseAction: jest.fn(),
  resolveGenjutsuPrices: jest.fn(async (items) => items),
}))

const categoryFetch = fetchTrendCategory as jest.MockedFunction<typeof fetchTrendCategory>
const adminAction = adminShowcaseAction as jest.Mock

const makeCard = (id: number, title: string, kind: 'image' | 'video' = 'image'): ShowcaseTrend => ({
  id, title, description: 'Публичное описание',
  category: kind === 'video' ? 'video' : 'photo',
  prompt_text: '', tags: ['trend'],
  model: null, likes: 0, uses_count: 0, successful_runs_count: 0, author_id: 1,
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


test('admin keeps existing preview edit and deactivate actions in the showcase', () => {
  const edit = jest.fn()
  const remove = jest.fn()
  render(<TrendShowcase categories={catalog} onRepeat={jest.fn()} onShare={jest.fn()} onEdit={edit} onRemove={remove} />)
  fireEvent.click(screen.getByRole('button', { name: 'Открыть тренд Свечи в торте' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Редактировать' }))
  expect(edit).toHaveBeenCalledWith(image)
  fireEvent.click(screen.getByRole('button', { name: 'Открыть тренд Свечи в торте' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Убрать тренд' }))
  expect(remove).toHaveBeenCalledWith(image)
})

test('changing to an unavailable folder never exposes stale items for destructive mutations', async () => {
  adminAction.mockResolvedValue({ items: [makeCard(99, 'Search suggestion')], has_more: false, total: 1, page: 1 })
  const other = { ...catalog[0], id: 8, title: 'Другой раздел', emoji: '🎵', revision: 1, items: [] }
  categoryFetch.mockImplementation(async (id) => {
    if (id === 8) throw new Error('База временно недоступна')
    return { category: catalog[0], items: [image, video], page: 1, total: 2, has_more: false }
  })
  render(<TrendCategoryManager open={true} onOpenChange={jest.fn()} categories={[catalog[0], other]}
    onRefresh={jest.fn().mockResolvedValue(undefined)} />)
  fireEvent.click(screen.getByRole('button', { name: /^🧁 Видео на День рождения/ }))
  await screen.findByText('Свечи в торте')
  fireEvent.click(screen.getByRole('button', { name: /^🎵 Другой раздел/ }))
  await screen.findByRole('alert')
  expect(screen.queryByText('Свечи в торте')).not.toBeInTheDocument()
  expect(screen.getByText('База временно недоступна')).toBeInTheDocument()
  await screen.findByText('Search suggestion')
  const add = screen.getByRole('button', { name: /Добавить/ })
  expect(add).toBeDisabled()
  expect(adminAction).not.toHaveBeenCalledWith(expect.objectContaining({ op: 'set_items' }))
})


test('legacy video preview without a file extension uses catalog kind rather than an image tag', () => {
  const signedVideo = {
    ...makeCard(55, 'Подписанное видео', 'video'),
    preview_url: 'https://cdn.example/preview/55?signature=valid',
    generation_settings: { kind: 'video' },
  } as ShowcaseTrend
  const folder = { ...catalog[0], items: [signedVideo], total: 1 }
  render(<TrendShowcase categories={[folder]} onRepeat={jest.fn()} onShare={jest.fn()} />)
  const tile = screen.getByRole('button', { name: 'Открыть тренд Подписанное видео' })
  expect(tile.querySelector('video')).toBeInTheDocument()
  expect(tile.querySelector('img')).not.toBeInTheDocument()
  fireEvent.click(tile)
  expect(within(screen.getByRole('dialog')).getByText('Подписанное видео')).toBeInTheDocument()
  expect(screen.getByRole('dialog').querySelector('video')).toBeInTheDocument()
})

test('category-specific draft dates and move targets do not bleed between shared trend placements', async () => {
  const sharedA = { ...image, badge: 'new' as const, badge_until: '2027-01-03' }
  const sharedB = { ...image, badge: 'new' as const, badge_until: '2028-02-04' }
  const folderA = { ...catalog[0], items: [sharedA], total: 1 }
  const folderB = { ...catalog[0], id: 8, title: 'Вторая папка', emoji: '🎵', revision: 7, items: [sharedB], total: 1 }
  categoryFetch.mockImplementation(async (id) => ({
    category: id === 7 ? folderA : folderB,
    items: id === 7 ? [sharedA] : [sharedB],
    total: 1, page: 1, has_more: false,
  }))
  adminAction.mockImplementation(async (action) => action.op === 'search_trends'
    ? { items: [], total: 0, page: 1, has_more: false }
    : { revision: 8 })
  render(<TrendCategoryManager open={true} onOpenChange={jest.fn()} categories={[folderA, folderB]}
    onRefresh={jest.fn().mockResolvedValue(undefined)} />)
  fireEvent.click(screen.getByRole('button', { name: /^🧁 Видео на День рождения/ }))
  const dateA = await screen.findByLabelText('Новинка до для Свечи в торте')
  expect(dateA).toHaveValue('2027-01-03')
  fireEvent.change(dateA, { target: { value: '2030-03-03' } })
  fireEvent.change(screen.getByRole('combobox', { name: 'Переместить Свечи в торте в категорию' }), {
    target: { value: '8' },
  })
  expect(screen.getByRole('button', { name: 'Перенести' })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: /^🎵 Вторая папка/ }))
  const dateB = await screen.findByLabelText('Новинка до для Свечи в торте')
  expect(dateB).toHaveValue('2028-02-04')
  expect(screen.getByRole('combobox', { name: 'Переместить Свечи в торте в категорию' })).toHaveValue('')
  expect(screen.queryByRole('button', { name: 'Перенести' })).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Сохранить новинку' }))
  await waitFor(() => expect(adminAction).toHaveBeenCalledWith({
    op: 'set_badge', category_id: 8, trend_id: 21, revision: 7,
    badge: 'new', badge_until: '2028-02-04',
  }))
})


test('admin can inspect durable history with signed actor and before/after state', async () => {
  adminAction.mockImplementation(async (action) => action.op === 'history' ? [{
    id: 'audit-1',
    action: 'update',
    actor_telegram_id: 999999999,
    category_id: 7,
    trend_id: null,
    before: { title: 'Старое название' },
    after: { title: 'Новое название' },
    created_at: '2026-10-15 10:30:00',
  }] : { items: [], total: 0, page: 1, has_more: false })
  render(<TrendCategoryManager open={true} onOpenChange={jest.fn()} categories={catalog}
    onRefresh={jest.fn().mockResolvedValue(undefined)} />)
  fireEvent.click(screen.getByRole('button', { name: 'Показать историю' }))
  await waitFor(() => expect(adminAction).toHaveBeenCalledWith({ op: 'history', limit: 30 }))
  expect(await screen.findByText(/update · Telegram 999999999/)).toBeInTheDocument()
  fireEvent.click(screen.getByText('Посмотреть до и после'))
  expect(screen.getByText(/Старое название/)).toBeInTheDocument()
  expect(screen.getByText(/Новое название/)).toBeInTheDocument()
})



test('WAN live tile and repeat modal show server-authoritative lower-bound price', () => {
  const wan = { ...makeCard(2075, 'Wan с фиксированным видео', 'video'), model: 'wan_3',
    repeat_cost: null, repeat_price_hint: { amount: 22, kind: 'from' as const },
    generation_settings: { kind: 'video' as const, duration: 11, resolution: '480P' },
  } as ShowcaseTrend
  render(<TrendShowcase categories={[{ ...catalog[0], items: [wan], total: 1 }]}
    onRepeat={jest.fn()} onShare={jest.fn()} />)
  expect(screen.getByRole('button', { name: 'Открыть тренд Wan с фиксированным видео' }))
    .toHaveTextContent('от 22🍌')
  fireEvent.click(screen.getByRole('button', { name: 'Открыть тренд Wan с фиксированным видео' }))
  expect(within(screen.getByRole('dialog')).getByRole('button', { name: /Повторить · от 22🍌/ })).toBeEnabled()
})


test('admin repetition counts stay visible on live tiles and preview for all folders', async () => {
  const favorite = { ...makeCard(201, 'Пользовательский тренд', 'video'), uses_count: 502, successful_runs_count: 328 }
  const young = { ...makeCard(202, 'Новый тренд'), uses_count: 17, successful_runs_count: 0 }
  const groups = [
    { ...catalog[0], total: 2, items: [favorite, young] },
    { ...catalog[0], id: 8, title: 'Другие', total: 1, items: [favorite] },
  ]
  categoryFetch.mockImplementation(async (id, page) => ({
    category: groups.find(group => group.id === id)!, items: id === 8 ? [favorite] : [favorite, young],
    page, total: id === 8 ? 1 : 2, has_more: false,
  }))
  render(<TrendShowcase isAdmin categories={groups} onRepeat={jest.fn()} onShare={jest.fn()} />)
  const firstTile = screen.getAllByRole('button', { name: 'Открыть тренд Пользовательский тренд' })[0]
  expect(firstTile).toHaveTextContent('328 повторов')
  expect(firstTile).not.toHaveTextContent('502')
  expect(screen.getByRole('button', { name: 'Открыть тренд Новый тренд' })).toHaveTextContent('0 повторов')
  fireEvent.click(firstTile)
  const preview = screen.getByRole('dialog')
  expect(within(preview).getByText('✅ Успешных повторов: 328')).toBeInTheDocument()
  fireEvent.click(within(preview).getByRole('button', { name: 'Close' }))
  fireEvent.click(screen.getByRole('button', { name: 'Все тренды категории Другие' }))
  await waitFor(() => expect(categoryFetch).toHaveBeenCalledWith(8, 1, 24))
  const paginatedTile = await screen.findByRole('button', { name: 'Открыть тренд Пользовательский тренд' })
  expect(paginatedTile).toHaveTextContent('328 повторов')
})

test('legacy card without a confirmed success count is not mislabeled zero', () => {
  const legacy = makeCard(1234, 'Данные не загрузились')
  delete legacy.successful_runs_count
  render(<TrendShowcase isAdmin categories={[{ ...catalog[0], items: [legacy] }]} onRepeat={jest.fn()} onShare={jest.fn()} />)
  const tile = screen.getByRole('button', { name: 'Открыть тренд Данные не загрузились' })
  expect(tile).not.toHaveTextContent('0 повторов')
})



test('completed counter uses correct Russian form for one and several repeats', () => {
  const counts = [0, 1, 2, 4, 5, 11, 21]
  const expected = ['0 повторов', '1 повтор', '2 повтора', '4 повтора', '5 повторов', '11 повторов', '21 повтор']
  const cards = counts.map((count, i) => ({
    ...makeCard(500 + i, 'Контроль ' + count), successful_runs_count: count,
  }))
  render(<TrendShowcase isAdmin categories={[{ ...catalog[0], total: cards.length, items: cards }]}
    onRepeat={jest.fn()} onShare={jest.fn()} />)
  for (let i = 0; i < counts.length; i += 1) {
    expect(screen.getByRole('button', { name: 'Открыть тренд Контроль ' + counts[i] })).toHaveTextContent(expected[i])
  }
})


test('viewer never sees cached admin counters on shelves, preview or paginated category', async () => {
  const counted = { ...video, successful_runs_count: 328, repeat_cost: 14 }
  const zero = { ...image, successful_runs_count: 0 }
  const folders = [{ ...catalog[0], items: [counted, zero], total: 2 }]
  categoryFetch.mockResolvedValue({ category: folders[0], items: [counted, zero], page: 1, total: 2, has_more: false })
  const onRepeat = jest.fn()
  render(<TrendShowcase categories={folders} onRepeat={onRepeat} onShare={jest.fn()} />)
  expect(screen.queryAllByLabelText(/Успешных повторов/)).toHaveLength(0)
  expect(screen.getByText('Новинка')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Открыть тренд Видео с эффектами' })).toHaveTextContent('14🍌')
  fireEvent.click(screen.getByRole('button', { name: 'Все тренды категории Видео на День рождения' }))
  await waitFor(() => expect(categoryFetch).toHaveBeenCalledWith(7, 1, 24))
  const tile = await screen.findByRole('button', { name: 'Открыть тренд Видео с эффектами' })
  expect(tile).not.toHaveTextContent('328')
  expect(screen.queryAllByLabelText(/Успешных повторов/)).toHaveLength(0)
  fireEvent.click(tile)
  const preview = screen.getByRole('dialog')
  expect(preview).not.toHaveTextContent(/Успешных повторов/)
  fireEvent.click(within(preview).getByRole('button', { name: /Повторить/ }))
  expect(onRepeat).toHaveBeenCalledWith(counted)
})

test('revoking administrator role hides statistics in an already open preview', () => {
  const folders = [{ ...catalog[0], items: [{ ...image, successful_runs_count: 7 }] }]
  const props = { categories: folders, onRepeat: jest.fn(), onShare: jest.fn(), onEdit: jest.fn() }
  const view = render(<TrendShowcase {...props} isAdmin />)
  fireEvent.click(screen.getByRole('button', { name: 'Открыть тренд Свечи в торте' }))
  expect(within(screen.getByRole('dialog')).getByLabelText('Успешных повторов: 7')).toBeInTheDocument()
  view.rerender(<TrendShowcase {...props} isAdmin={false} />)
  expect(screen.queryAllByLabelText(/Успешных повторов/)).toHaveLength(0)
  expect(screen.getByRole('dialog')).not.toHaveTextContent('7')
})

test('content save reloads the currently expanded category with the renamed card', async () => {
  const props = { categories: catalog, onRepeat: jest.fn(), onShare: jest.fn(), isAdmin: true }
  const { rerender } = render(<TrendShowcase {...props} refreshVersion={0} />)
  fireEvent.click(screen.getByRole('button', { name: 'Все тренды категории Видео на День рождения' }))
  await screen.findByRole('button', { name: 'Открыть тренд Свечи в торте' })
  categoryFetch.mockResolvedValueOnce({ category: catalog[0], items: [{ ...image, title: 'Новое название' }], page: 1, total: 1, has_more: false })
  rerender(<TrendShowcase {...props} refreshVersion={1} />)
  expect(await screen.findByRole('button', { name: 'Открыть тренд Новое название' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Открыть тренд Свечи в торте' })).not.toBeInTheDocument()
})
