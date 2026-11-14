import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VkGenerationPanel } from '../vk-generation-panel'
import { fetchVkSavedReferences,
  fetchVkGenerationClaim, fetchVkModelCatalog, repeatVkTrend, uploadVkImage,
  type VkPublicTrend,
} from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchVkSavedReferences: jest.fn().mockResolvedValue([]),
  fetchVkGenerationClaim: jest.fn(),
  fetchVkModelCatalog: jest.fn(),
  repeatVkTrend: jest.fn(),
  uploadVkImage: jest.fn(),
}))

const VIDEO: VkPublicTrend = {
  id: 31, title: 'Фильм с лисами', description: '',
  preview_url: null, preview_poster_url: null,
  generation_type: 'video', can_repeat_in_app: true,
}

const file = () => new File(['image-bytes'], 'my-photo.jpg', { type: 'image/jpeg' })

beforeEach(() => {
  jest.resetAllMocks()
  jest.mocked(fetchVkSavedReferences).mockResolvedValue([])
  jest.mocked(uploadVkImage).mockResolvedValue(
    'https://neuromixbot.com/uploads/vk-refs/image/2001/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg',
  )
})

test('VK user repeats a video trend using server-owned recipe, not client prompt or model', async () => {
  jest.mocked(repeatVkTrend)
    .mockResolvedValueOnce({ ok: true, task_id: 0, cost: 12, quote_only: true })
    .mockResolvedValueOnce({ ok: true, task_id: 76, cost: 12 })
  render(<VkGenerationPanel trend={VIDEO} onClose={jest.fn()} />)
  fireEvent.change(screen.getByLabelText('Фото-референсы'), { target: { files: [file()] } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByRole('button', { name: 'Создать за 12 🍌' })).toBeInTheDocument()
  expect(repeatVkTrend).toHaveBeenCalledWith({
    trend_id: 31, user_values: {},
    reference_urls: ['https://neuromixbot.com/uploads/vk-refs/image/2001/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg'],
    quote_only: true,
  })
  fireEvent.click(screen.getByRole('button', { name: 'Создать за 12 🍌' }))
  expect(await screen.findByText(/Задача #76 создана/)).toBeInTheDocument()
  expect(jest.mocked(repeatVkTrend).mock.calls[1][0]).toEqual(expect.objectContaining({
    trend_id: 31, expected_cost: 12,
    client_request_id: expect.stringMatching(/^vk_[a-f0-9]{32}$/),
  }))
  expect(fetchVkModelCatalog).not.toHaveBeenCalled()
})

test('unknown paid video trend response resolves exactly the native VIDEO claim', async () => {
  jest.mocked(repeatVkTrend)
    .mockResolvedValueOnce({ ok: true, task_id: 0, cost: 12, quote_only: true })
    .mockRejectedValueOnce(new Error('VK WebView timeout'))
  jest.mocked(fetchVkGenerationClaim).mockResolvedValue({
    ok: true, found: true, task_id: 77,
    task_type: 'video', status: 'processing', cost: 12,
  })
  render(<VkGenerationPanel trend={VIDEO} onClose={jest.fn()} />)
  fireEvent.change(screen.getByLabelText('Фото-референсы'), { target: { files: [file()] } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Создать за 12 🍌' }))
  expect(await screen.findByText(/Задача #77 создана/)).toBeInTheDocument()
  expect(fetchVkGenerationClaim).toHaveBeenCalledWith(
    jest.mocked(repeatVkTrend).mock.calls[1][0].client_request_id,
  )
  expect(repeatVkTrend).toHaveBeenCalledTimes(2)
})

test('ambiguous VIDEO trend lookup never retries automatically and preserves original key', async () => {
  jest.mocked(repeatVkTrend)
    .mockResolvedValueOnce({ ok: true, task_id: 0, cost: 12, quote_only: true })
    .mockRejectedValueOnce(new Error('connection reset'))
    .mockResolvedValueOnce({ ok: true, task_id: 79, cost: 12 })
  jest.mocked(fetchVkGenerationClaim).mockRejectedValue(new Error('native lookup unavailable'))
  render(<VkGenerationPanel trend={VIDEO} onClose={jest.fn()} />)
  fireEvent.change(screen.getByLabelText('Фото-референсы'), { target: { files: [file()] } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Создать за 12 🍌' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Статус генерации пока неясен')
  expect(repeatVkTrend).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'Создать за 12 🍌' }))
  expect(await screen.findByText(/Задача #79 создана/)).toBeInTheDocument()
  expect(jest.mocked(repeatVkTrend).mock.calls[2][0].client_request_id)
    .toEqual(jest.mocked(repeatVkTrend).mock.calls[1][0].client_request_id)
})

test('VIDEO trend never accepts a PHOTO claim belonging to another request', async () => {
  jest.mocked(repeatVkTrend)
    .mockResolvedValueOnce({ ok: true, task_id: 0, cost: 12, quote_only: true })
    .mockRejectedValueOnce(new Error('transport lost'))
  jest.mocked(fetchVkGenerationClaim).mockResolvedValue({
    ok: true, found: true, task_id: 101,
    task_type: 'photo', status: 'processing', cost: 12,
  })
  render(<VkGenerationPanel trend={VIDEO} onClose={jest.fn()} />)
  fireEvent.change(screen.getByLabelText('Фото-референсы'), { target: { files: [file()] } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Создать за 12 🍌' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Статус генерации пока неясен')
  expect(screen.queryByText(/Задача #101 создана/)).not.toBeInTheDocument()
  await waitFor(() => expect(repeatVkTrend).toHaveBeenCalledTimes(2))
})
