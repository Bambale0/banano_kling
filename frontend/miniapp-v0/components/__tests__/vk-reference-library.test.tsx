import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VkReferenceLibrary } from '../vk-reference-library'
import { VkGenerationPanel } from '../vk-generation-panel'
import {
  fetchVkSavedReferences, saveVkSavedReference, forgetVkSavedReference,
  uploadVkImage, fetchVkModelCatalog, repeatVkTrend,
  type VkSavedReference, type VkPublicTrend,
} from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchVkSavedReferences: jest.fn(),
  saveVkSavedReference: jest.fn(),
  forgetVkSavedReference: jest.fn(),
  uploadVkImage: jest.fn(),
  fetchVkModelCatalog: jest.fn(),
  repeatVkTrend: jest.fn(),
  fetchVkGenerationClaim: jest.fn(),
}))

const REF: VkSavedReference = {
  reference_id: 'a'.repeat(32),
  name: 'Моя Лиса',
  url: 'https://neuromixbot.com/uploads/vk-refs/image/2001/' + 'b'.repeat(32) + '.jpg',
  created_at: '2026-11-13 20:00:00',
}

beforeEach(() => {
  jest.clearAllMocks()
  jest.mocked(fetchVkSavedReferences).mockResolvedValue([REF])
  jest.mocked(saveVkSavedReference).mockResolvedValue(REF)
  jest.mocked(forgetVkSavedReference).mockResolvedValue(true)
  jest.mocked(uploadVkImage).mockResolvedValue(REF.url)
})

test('VK profile displays only owner supplied library with no Telegram credentials or balance', async () => {
  render(<VkReferenceLibrary canUpload={false} />)
  expect(await screen.findByText('Моя Лиса')).toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'Моя Лиса' })).toHaveAttribute('src', REF.url)
  expect(screen.queryByRole('button', { name: 'Сохранить фото' })).not.toBeInTheDocument()
  expect(screen.queryByText('Telegram ID')).not.toBeInTheDocument()
  expect(fetchVkSavedReferences).toHaveBeenCalledWith(expect.any(AbortSignal))
})

test('new VK photo upload is saved once with stable metadata after success', async () => {
  render(<VkReferenceLibrary canUpload />)
  await screen.findByText('Моя Лиса')
  fireEvent.change(screen.getByLabelText('Фото в VK-библиотеку'), {
    target: { files: [new File(['image-bytes'], 'Леся.jpg', { type: 'image/jpeg' })] },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить фото' }))
  expect(await screen.findByText('Фото добавлено в библиотеку ВКонтакте.')).toBeInTheDocument()
  expect(uploadVkImage).toHaveBeenCalledTimes(1)
  expect(saveVkSavedReference).toHaveBeenCalledWith(REF.url, 'Леся.jpg')
})

test('failed metadata write can be retried without uploading the same image again', async () => {
  jest.mocked(saveVkSavedReference).mockRejectedValueOnce(new Error('Timeout')).mockResolvedValueOnce(REF)
  render(<VkReferenceLibrary canUpload />)
  await screen.findByText('Моя Лиса')
  fireEvent.change(screen.getByLabelText('Фото в VK-библиотеку'), {
    target: { files: [new File(['image-bytes'], 'Леся.jpg', { type: 'image/jpeg' })] },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить фото' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Timeout')
  fireEvent.click(screen.getByRole('button', { name: 'Повторить сохранение' }))
  expect(await screen.findByText('Фото добавлено в библиотеку ВКонтакте.')).toBeInTheDocument()
  expect(uploadVkImage).toHaveBeenCalledTimes(1)
  expect(saveVkSavedReference).toHaveBeenCalledTimes(2)
  expect(jest.mocked(saveVkSavedReference).mock.calls[0][0])
    .toBe(jest.mocked(saveVkSavedReference).mock.calls[1][0])
})

test('forget deletes only a bookmarked reference and preserves external image bytes', async () => {
  render(<VkReferenceLibrary canUpload={false} />)
  await screen.findByText('Моя Лиса')
  fireEvent.click(screen.getByRole('button', { name: 'Убрать из сохранённых' }))
  expect(await screen.findByText('Фото убрано из сохранённых. Исходный файл не удалён.')).toBeInTheDocument()
  expect(forgetVkSavedReference).toHaveBeenCalledWith(REF.reference_id)
  expect(screen.queryByText('Моя Лиса')).not.toBeInTheDocument()
  expect(uploadVkImage).not.toHaveBeenCalled()
})

test('VK video trend uses saved own reference without a new upload or exposing author prompt', async () => {
  const trend: VkPublicTrend = {
    id: 32, title: 'Тренд с лисой', description: '',
    preview_url: null, preview_poster_url: null, generation_type: 'video',
    can_repeat_in_app: true,
  }
  jest.mocked(repeatVkTrend).mockResolvedValue({ ok: true, task_id: 0, cost: 9, quote_only: true })
  render(<VkGenerationPanel trend={trend} onClose={() => {}} />)
  const checkbox = await screen.findByRole('checkbox', { name: /Использовать/ })
  fireEvent.click(checkbox)
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByRole('button', { name: 'Создать за 9 🍌' })).toBeInTheDocument()
  expect(repeatVkTrend).toHaveBeenCalledWith({
    trend_id: 32, reference_urls: [REF.url], user_values: {}, quote_only: true,
  })
  expect(uploadVkImage).not.toHaveBeenCalled()
})

test('changing selected saved photo invalidates stale paid VK quote', async () => {
  const trend: VkPublicTrend = {
    id: 33, title: 'Тренд', description: '', preview_url: null,
    preview_poster_url: null, generation_type: 'image', can_repeat_in_app: true,
  }
  jest.mocked(repeatVkTrend).mockResolvedValue({ ok: true, task_id: 0, cost: 2, quote_only: true })
  render(<VkGenerationPanel trend={trend} onClose={() => {}} />)
  const checkbox = await screen.findByRole('checkbox', { name: /Использовать/ })
  fireEvent.click(checkbox)
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await screen.findByRole('button', { name: 'Создать за 2 🍌' })
  fireEvent.click(checkbox)
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Создать за 2 🍌' })).not.toBeInTheDocument())
})
