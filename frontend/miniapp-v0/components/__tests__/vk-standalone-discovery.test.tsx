import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VkStandaloneDiscovery } from '../vk-standalone-discovery'
import { fetchVkPublicCategory, fetchVkPublicDiscovery, fetchVkNativeState, repeatVkTrend, generateVkImage, uploadVkImage } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchVkPublicDiscovery: jest.fn(),
  fetchVkPublicCategory: jest.fn(),
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


test('signed VK-only user quotes and repeats a photo trend without Telegram', async () => {
  jest.mocked(fetchVkPublicDiscovery).mockResolvedValue({
    ok: true, can_generate_in_app: true,
    categories: [{ id: 77, title: 'Портреты', emoji: '🎨', total: 1,
      items: [{ ...card(5, 'Ретро портрет'), can_repeat_in_app: true,
        user_fields: [{ key: 'age', label: 'Возраст', required: true }] }] }],
  })
  jest.mocked(uploadVkImage).mockResolvedValue('https://example.test/uploads/vk-refs/image/2001/' + 'a'.repeat(32) + '.jpg')
  jest.mocked(repeatVkTrend)
    .mockResolvedValueOnce({ ok: true, task_id: 0, cost: 2.5, quote_only: true })
    .mockResolvedValueOnce({ ok: true, task_id: 73, cost: 2.5 })
  render(<VkStandaloneDiscovery />)
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить «Ретро портрет»' }))
  fireEvent.change(screen.getByLabelText('Возраст'), { target: { value: '33' } })
  const file = new File(['fake image'], 'face.jpg', { type: 'image/jpeg' })
  fireEvent.change(screen.getByLabelText('Фото-референсы'), { target: { files: [file] } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByRole('button', { name: 'Создать за 2.5 🍌' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Создать за 2.5 🍌' }))
  expect(await screen.findByText(/Задача #73 создана/)).toBeInTheDocument()
  const paid = jest.mocked(repeatVkTrend).mock.calls[1][0]
  expect(paid.trend_id).toBe(5)
  expect(paid.expected_cost).toBe(2.5)
  expect(paid.user_values).toEqual({ age: '33' })
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
