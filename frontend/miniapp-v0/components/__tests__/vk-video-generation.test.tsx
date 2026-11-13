import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VkGenerationPanel } from '../vk-generation-panel'
import {
  fetchVkGenerationClaim, fetchVkModelCatalog, generateVkVideo, uploadVkImage,
} from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchVkModelCatalog: jest.fn(),
  generateVkVideo: jest.fn(),
  fetchVkGenerationClaim: jest.fn(),
  uploadVkImage: jest.fn(),
}))

beforeEach(() => {
  jest.resetAllMocks()
  jest.mocked(fetchVkModelCatalog).mockResolvedValue({
    ok: true, photo_models: [],
    video_models: [{
      id: 'v3_std', label: 'Kling Standard', ratios: ['16:9', '9:16'],
      duration_min: 5, duration_max: 6, durations: [5, 6],
      scenarios: ['text', 'imgtxt'], max_image_references: 2,
    }],
  })
})

test('VK-only video quotes and submits native model duration, without Telegram wallet', async () => {
  jest.mocked(generateVkVideo)
    .mockResolvedValueOnce({ ok: true, task_id: 0, cost: 15, quote_only: true })
    .mockResolvedValueOnce({ ok: true, task_id: 456, cost: 15 })
  render(<VkGenerationPanel kind="video" onClose={jest.fn()} />)
  expect(await screen.findByRole('option', { name: 'Kling Standard' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Промпт'), { target: { value: 'A fox dancing' } })
  fireEvent.change(screen.getByLabelText('Длительность'), { target: { value: '6' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByRole('button', { name: 'Создать за 15 🍌' })).toBeInTheDocument()
  expect(generateVkVideo).toHaveBeenCalledWith(expect.objectContaining({
    model: 'v3_std', prompt: 'A fox dancing', aspect: '16:9', duration: 6,
    reference_photos: [], quote_only: true,
  }))
  fireEvent.click(screen.getByRole('button', { name: 'Создать за 15 🍌' }))
  expect(await screen.findByText(/Задача #456 создана/)).toBeInTheDocument()
  expect(generateVkVideo).toHaveBeenCalledTimes(2)
  const paid = jest.mocked(generateVkVideo).mock.calls[1][0]
  expect(paid.client_request_id).toMatch(/^vk_[0-9a-f]{32}$/)
  expect(paid.expected_cost).toBe(15)
})

test('video submit with unknown network outcome reconciles the same native claim', async () => {
  jest.mocked(generateVkVideo)
    .mockResolvedValueOnce({ ok: true, task_id: 0, cost: 12, quote_only: true })
    .mockRejectedValueOnce(new Error('transport timeout'))
  jest.mocked(fetchVkGenerationClaim).mockResolvedValue({
    ok: true, found: true, task_type: 'video', task_id: 982,
    status: 'processing', cost: 12,
  })
  render(<VkGenerationPanel kind="video" onClose={jest.fn()} />)
  await screen.findByRole('option', { name: 'Kling Standard' })
  fireEvent.change(screen.getByLabelText('Промпт'), { target: { value: 'A fox dancing' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Создать за 12 🍌' }))
  expect(await screen.findByText(/Задача #982 создана/)).toBeInTheDocument()
  expect(generateVkVideo).toHaveBeenCalledTimes(2)
  expect(fetchVkGenerationClaim).toHaveBeenCalledWith(
    jest.mocked(generateVkVideo).mock.calls[1][0].client_request_id,
  )
})

test('unknown video claim preserves the paid request key for explicit retry, not auto-submit', async () => {
  jest.mocked(generateVkVideo)
    .mockResolvedValueOnce({ ok: true, task_id: 0, cost: 12, quote_only: true })
    .mockRejectedValueOnce(new Error('timeout'))
    .mockResolvedValueOnce({ ok: true, task_id: 983, cost: 12 })
  jest.mocked(fetchVkGenerationClaim).mockRejectedValue(new Error('read unavailable'))
  render(<VkGenerationPanel kind="video" onClose={jest.fn()} />)
  await screen.findByRole('option', { name: 'Kling Standard' })
  fireEvent.change(screen.getByLabelText('Промпт'), { target: { value: 'A fox dancing' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Создать за 12 🍌' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Статус генерации пока неясен')
  expect(generateVkVideo).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'Создать за 12 🍌' }))
  expect(await screen.findByText(/Задача #983 создана/)).toBeInTheDocument()
  const a = jest.mocked(generateVkVideo).mock.calls[1][0].client_request_id
  const b = jest.mocked(generateVkVideo).mock.calls[2][0].client_request_id
  expect(b).toEqual(a)
})

test('video does not offer fake capabilities or submit unsupported references', async () => {
  jest.mocked(generateVkVideo).mockResolvedValue({ ok: true, task_id: 0, cost: 12, quote_only: true })
  jest.mocked(uploadVkImage).mockResolvedValue('https://example.test/photo.jpg')
  render(<VkGenerationPanel kind="video" onClose={jest.fn()} />)
  await screen.findByRole('option', { name: 'Kling Standard' })
  fireEvent.change(screen.getByLabelText('Промпт'), { target: { value: 'A fox dancing' } })
  const files = [1, 2, 3].map(i => new File(['image'], 'ref' + i + '.jpg', { type: 'image/jpeg' }))
  fireEvent.change(screen.getByLabelText('Фото-референсы'), { target: { files } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('не более 2')
  expect(generateVkVideo).not.toHaveBeenCalled()
})

test('video cannot be quoted without a native worker model', async () => {
  jest.mocked(fetchVkModelCatalog).mockResolvedValue({ ok: true, photo_models: [], video_models: [] })
  render(<VkGenerationPanel kind="video" onClose={jest.fn()} />)
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('доступных моделей'))
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  expect(generateVkVideo).not.toHaveBeenCalled()
})
