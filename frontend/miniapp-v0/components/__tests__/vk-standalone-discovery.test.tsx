import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { VkStandaloneDiscovery } from '../vk-standalone-discovery'
import { fetchVkPublicCategory, fetchVkPublicDiscovery, fetchVkPublicTrend, fetchVkPublicFeedItem, fetchVkNativeState, repeatVkTrend, generateVkImage, uploadVkImage } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchVkPublicDiscovery: jest.fn(),
  fetchVkPublicCategory: jest.fn(),
  fetchVkPublicTrend: jest.fn(),
  fetchVkPublicFeedItem: jest.fn(),
  fetchVkNativeState: jest.fn(),
  repeatVkTrend: jest.fn(),
  generateVkImage: jest.fn(),
  uploadVkImage: jest.fn(),
}))

const card = (id: number, title: string) => ({
  id, title, description: 'Фото по референсу',
  preview_url: 'https://example.test/public.jpg',
  preview_poster_url: null,
  generation_type: 'image' as const,
})

beforeEach(() => {
  window.history.replaceState({}, '', '/')
  jest.resetAllMocks()
  jest.mocked(fetchVkNativeState).mockResolvedValue({
    ok: true, registered: true, balance: 12.5, is_blocked: false,
    tasks: [{ task_id: 7, task_type: 'photo', model: 'nano_banana_pro',
      status: 'completed', cost: 2.5, result_url: 'https://example.test/result.jpg',
      created_at: '2026-11-09 12:00:00' }],
  })
  jest.mocked(fetchVkPublicDiscovery).mockResolvedValue({
    ok: true,
    can_generate_in_app: false,
    categories: [
      { id: 77, title: 'Портреты', emoji: '🎨', total: 30, items: [card(5, 'Ретро портрет')] },
    ],
  })
  jest.mocked(fetchVkPublicCategory).mockImplementation(async (_id, page = 1) => ({
    ok: true, category: { id: 77, title: 'Портреты', emoji: '🎨' },
    page, has_more: page === 1, can_generate_in_app: false,
    items: [page === 1 ? card(6, 'Дневной портрет') : card(7, 'Вечерний портрет')],
  }))
})

test('VK-only can browse the curated trends without Telegram and open a category', async () => {
  render(<VkStandaloneDiscovery />)
  expect(await screen.findByText('Ретро портрет')).toBeInTheDocument()
  expect(screen.getByText(/Просмотр открыт без Telegram/)).toBeInTheDocument()
  expect(screen.queryByText('Привяжите Telegram')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Все (30)' }))
  expect(await screen.findByText('Дневной портрет')).toBeInTheDocument()
  expect(fetchVkPublicCategory).toHaveBeenCalledWith(77, 1, expect.anything())
  fireEvent.click(screen.getByRole('button', { name: 'Показать ещё' }))
  expect(await screen.findByText('Вечерний портрет')).toBeInTheDocument()
  expect(screen.getByText('Дневной портрет')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '← Ко всем трендам' }))
  expect(await screen.findByText('Ретро портрет')).toBeInTheDocument()
})

test('VK-only can browse the public feed without a billing action', async () => {
  jest.mocked(fetchVkPublicDiscovery).mockImplementation(async view => view === 'feed'
    ? { ok: true, can_generate_in_app: false, items: [{
      id: 9, generation_type: 'video',
      preview_url: null, result_url: 'https://example.test/public.mp4', likes_count: 4,
    }] }
    : { ok: true, can_generate_in_app: false, categories: [] })
  render(<VkStandaloneDiscovery />)
  fireEvent.click(screen.getByRole('button', { name: 'Лента' }))
  await waitFor(() => expect(screen.getByText(/🎬 Видео · ❤ 4/)).toBeInTheDocument())
  expect(screen.getByText(/Оплачиваемый повтор непосредственно в Mini App/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Списать|Оплатить|Повторить/ })).not.toBeInTheDocument()
})

test('failed catalog read exposes a real retry', async () => {
  jest.mocked(fetchVkPublicDiscovery)
    .mockRejectedValueOnce(new Error('Сеть недоступна'))
    .mockResolvedValueOnce({ ok: true, can_generate_in_app: false, categories: [] })
  render(<VkStandaloneDiscovery />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Сеть недоступна')
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }))
  await waitFor(() => expect(fetchVkPublicDiscovery).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
})

test('VK-only sees native VK balance and its results without Telegram ID', async () => {
  render(<VkStandaloneDiscovery />)
  expect(await screen.findByText(/VK-баланс: 12.5/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Мои работы' }))
  expect(await screen.findByRole('link', { name: 'Открыть результат #7' }))
    .toHaveAttribute('href', 'https://example.test/result.jpg')
  expect(fetchVkNativeState).toHaveBeenCalled()
  expect(screen.queryByText('Telegram ID')).not.toBeInTheDocument()
})


test('incomplete native state does not blank trends or the work history', async () => {
  jest.mocked(fetchVkNativeState).mockResolvedValue({
    ok: true, registered: true, balance: 12.5, is_blocked: false,
    // The production API requires tasks, but an older client/mocked response
    // may omit it. Missing history must never crash the entire application.
  } as unknown as Awaited<ReturnType<typeof fetchVkNativeState>>)
  render(<VkStandaloneDiscovery />)
  expect(await screen.findByText('Ретро портрет')).toBeInTheDocument()
  expect(screen.getByText(/VK-баланс: 12.5/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Мои работы' }))
  expect(screen.getByRole('alert')).toHaveTextContent('История работ временно недоступна')
})

test('unfinished VK task refreshes automatically while work history is open, then stops', async () => {
  jest.useFakeTimers()
  try {
    const working = {
      ok: true as const, registered: true, balance: 12.5, is_blocked: false,
      tasks: [{ task_id: 95, task_type: 'photo', model: 'nano_banana_pro',
        status: 'processing', cost: 2.5, result_url: null, created_at: '2026-11-10 12:00:00' }],
    }
    const completed = {
      ...working, tasks: [{ ...working.tasks[0], status: 'completed',
        result_url: 'https://example.test/completed.jpg' }],
    }
    jest.mocked(fetchVkNativeState)
      .mockResolvedValueOnce(working)
      .mockResolvedValue(completed)
    render(<VkStandaloneDiscovery />)
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    fireEvent.click(screen.getByRole('button', { name: 'Мои работы' }))
    expect(screen.getByText(/#95/)).toBeInTheDocument()
    expect(fetchVkNativeState).toHaveBeenCalledTimes(1)
    await act(async () => {
      jest.advanceTimersByTime(15000)
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(fetchVkNativeState).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('link', { name: 'Открыть результат #95' }))
      .toHaveAttribute('href', 'https://example.test/completed.jpg')
    await act(async () => { jest.advanceTimersByTime(30000) })
    expect(fetchVkNativeState).toHaveBeenCalledTimes(2)
  } finally {
    jest.useRealTimers()
  }
})

test('signed VK-only user quotes and repeats a photo trend without Telegram', async () => {
  jest.mocked(fetchVkPublicDiscovery).mockResolvedValue({
    ok: true, can_generate_in_app: true,
    categories: [{ id: 77, title: 'Портреты', emoji: '🎨', total: 1,
      items: [{ ...card(5, 'Ретро портрет'), can_repeat_in_app: true,
        user_fields: [
          { key: 'age', label: 'Возраст', type: 'number', required: true },
          { key: 'date', label: 'Дата', type: 'date', required: true },
        ] }] }],
  })
  jest.mocked(uploadVkImage).mockResolvedValue('https://example.test/uploads/vk-refs/image/2001/' + 'a'.repeat(32) + '.jpg')
  jest.mocked(repeatVkTrend)
    .mockResolvedValueOnce({ ok: true, task_id: 0, cost: 2.5, quote_only: true })
    .mockResolvedValueOnce({ ok: true, task_id: 73, cost: 2.5 })
  render(<VkStandaloneDiscovery />)
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить «Ретро портрет»' }))
  expect(screen.getByLabelText('Возраст')).toHaveAttribute('type', 'number')
  expect(screen.getByLabelText('Дата')).toHaveAttribute('type', 'date')
  fireEvent.change(screen.getByLabelText('Возраст'), { target: { value: '33' } })
  fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '2026-11-10' } })
  const file = new File(['fake image'], 'face.jpg', { type: 'image/jpeg' })
  fireEvent.change(screen.getByLabelText('Фото-референсы'), { target: { files: [file] } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByRole('button', { name: 'Создать за 2.5 🍌' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Создать за 2.5 🍌' }))
  expect(await screen.findByText(/Задача #73 создана/)).toBeInTheDocument()
  const paid = jest.mocked(repeatVkTrend).mock.calls[1][0]
  expect(paid.trend_id).toBe(5)
  expect(paid.expected_cost).toBe(2.5)
  expect(paid.user_values).toEqual({ age: '33', date: '2026-11-10' })
  expect(paid.reference_urls).toHaveLength(1)
  expect(paid.client_request_id).toMatch(/^[A-Za-z0-9_-]{16,80}$/)
  expect(screen.queryByText('Привяжите Telegram')).not.toBeInTheDocument()
})

test('VK-only can quote and create an image using native VK wallet', async () => {
  jest.mocked(fetchVkPublicDiscovery).mockResolvedValue({
    ok: true, can_generate_in_app: true, categories: [],
  })
  jest.mocked(generateVkImage)
    .mockResolvedValueOnce({ ok: true, task_id: 0, cost: 2.5, quote_only: true })
    .mockResolvedValueOnce({ ok: true, task_id: 74, cost: 2.5 })
  render(<VkStandaloneDiscovery />)
  fireEvent.click(await screen.findByRole('button', { name: 'Создать фото' }))
  fireEvent.change(screen.getByLabelText('Промпт'), { target: { value: 'A castle on the moon' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Создать за 2.5 🍌' }))
  expect(await screen.findByText(/Задача #74 создана/)).toBeInTheDocument()
  expect(jest.mocked(generateVkImage).mock.calls[1][0]).toEqual(expect.objectContaining({
    prompt: 'A castle on the moon', expected_cost: 2.5, model: 'nano_banana_pro',
  }))
})


test('VK prompt deep link opens the exact public trend without Telegram and can repeat it', async () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=signed#prompt_5_ref_CODE')
  const deepTrend = { ...card(5, 'Тренд по ссылке'), can_repeat_in_app: true,
    share_link: 'https://vk.com/app123#prompt_5' }
  jest.mocked(fetchVkPublicTrend).mockResolvedValue({
    ok: true, item: deepTrend, can_generate_in_app: true,
  })
  render(<VkStandaloneDiscovery />)
  expect(await screen.findByText('Тренд по ссылке')).toBeInTheDocument()
  expect(fetchVkPublicTrend).toHaveBeenCalledWith(5, expect.anything())
  fireEvent.click(screen.getByRole('button', { name: 'Повторить «Тренд по ссылке»' }))
  expect(screen.getByRole('region', { name: 'Повтор тренда' })).toBeInTheDocument()
  expect(screen.queryByText('Привяжите Telegram')).not.toBeInTheDocument()
})

test('a video trend deep link opens the public preview and sharing URL, without fake photo repeat', async () => {
  window.history.replaceState({}, '', '/#prompt_8')
  jest.mocked(fetchVkPublicTrend).mockResolvedValue({
    ok: true, can_generate_in_app: true,
    item: { ...card(8, 'Видео по ссылке'), generation_type: 'video',
      can_repeat_in_app: false, share_link: 'https://vk.com/app123#prompt_8' },
  })
  render(<VkStandaloneDiscovery />)
  expect(await screen.findByText('Видео по ссылке')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Повторить «Видео по ссылке»' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Ссылка на «Видео по ссылке»' }))
  expect(screen.getByRole('textbox', { name: 'Ссылка на тренд' })).toHaveValue('https://vk.com/app123#prompt_8')
})

test('invalid or unavailable shared trend has a clear error and can return to catalog', async () => {
  window.history.replaceState({}, '', '/#prompt_999')
  jest.mocked(fetchVkPublicTrend).mockRejectedValue(new Error('Тренд не найден'))
  render(<VkStandaloneDiscovery />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Тренд не найден')
  fireEvent.click(screen.getByRole('button', { name: 'Вернуться к трендам' }))
  expect(await screen.findByText('Ретро портрет')).toBeInTheDocument()
})

test.each([
  ['feed', 'Публикация из ленты'],
  ['remix', 'Повтор публикации из ленты'],
] as const)('signed VK-only %s deep link opens a feed publication, never a trend', async (kind, label) => {
  window.history.replaceState({}, '', '/?vk_app_id=54880352&vk_user_id=2001&sign=signed#' + kind + '_370766_ref_27QT0YCB')
  jest.mocked(fetchVkPublicDiscovery).mockResolvedValue({
    ok: true, can_generate_in_app: false, items: [],
  })
  jest.mocked(fetchVkPublicFeedItem).mockResolvedValue({
    ok: true, item: {
      id: 370766, generation_type: 'video', model: 'seedance_2_5',
      preview_url: 'https://example.test/public-preview.mp4',
      preview_poster_url: 'https://example.test/public-poster.jpg',
      result_url: 'https://example.test/public-video.mp4', likes_count: 12,
      comments_count: 2, shares_count: 3, duration: 8, aspect_ratio: '9:16',
      feed_blurred: false, media_unavailable: false,
      share_link: 'https://vk.com/app54880352#feed_370766',
      can_repeat_in_app: false,
    },
  })
  render(<VkStandaloneDiscovery />)
  const detail = await screen.findByRole('region', { name: label })
  expect(detail).toHaveTextContent('Seedance')
  expect(detail.querySelector('video')).toHaveAttribute('src', 'https://example.test/public-video.mp4')
  expect(fetchVkPublicFeedItem).toHaveBeenCalledWith(370766, expect.anything())
  expect(fetchVkPublicTrend).not.toHaveBeenCalled()
  expect(detail).not.toHaveTextContent('Тренд по ссылке')
  expect(within(detail).queryByRole('button', { name: /Повторить|Оплатить|Создать за/ })).not.toBeInTheDocument()
  if (kind === 'remix') {
    expect(detail).toHaveTextContent('Повтор этой публикации в VK Mini App пока не подключён')
  }
  expect(screen.queryByText('HIDDEN_AUTHOR_PROMPT')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Вернуться к ленте' }))
  expect(window.location.hash).toBe('')
})

test('missing VK feed publication reports its own error instead of opening a numbered trend', async () => {
  window.history.replaceState({}, '', '/#feed_370766_ref_27QT0YCB')
  jest.mocked(fetchVkPublicFeedItem).mockRejectedValue(new Error('Публикация не найдена'))
  render(<VkStandaloneDiscovery />)
  const detail = await screen.findByRole('region', { name: 'Публикация из ленты' })
  expect(await within(detail).findByRole('alert')).toHaveTextContent('Публикация не найдена')
  expect(fetchVkPublicTrend).not.toHaveBeenCalled()
})
