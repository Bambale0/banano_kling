import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VkStandaloneDiscovery } from '../vk-standalone-discovery'
import { fetchVkPublicCategory, fetchVkPublicDiscovery } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchVkPublicDiscovery: jest.fn(),
  fetchVkPublicCategory: jest.fn(),
}))

const card = (id: number, title: string) => ({
  id, title, description: 'Фото по референсу',
  preview_url: 'https://example.test/public.jpg',
  preview_poster_url: null,
  generation_type: 'image' as const,
})

beforeEach(() => {
  jest.resetAllMocks()
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
