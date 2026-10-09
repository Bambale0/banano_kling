import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Wan3PrimeForm } from './wan3-prime-form'
import { generateWan3Prime, quoteWan3Prime, uploadWan3PrimeReference } from '@/lib/wan3-prime-api'

jest.mock('@/lib/wan3-prime-api', () => ({
  quoteWan3Prime: jest.fn(), generateWan3Prime: jest.fn(),
  uploadWan3PrimeReference: jest.fn(), importWan3PrimeReference: jest.fn(),
  fetchWan3PrimeOwnerRecipe: jest.fn(),
}))
const quote = { ok: true, quote_hash: 'quote-1', reserve_cost: 60,
  billing_duration_seconds: 30, source_video_duration_seconds: 2.5,
  tariff_missing: false, admin_free: false, auto_duration: true,
  settlement_notice: 'После генерации вернём неиспользованный резерв.' }

beforeEach(() => {
  jest.clearAllMocks()
  ;(quoteWan3Prime as jest.Mock).mockResolvedValue(quote)
  ;(generateWan3Prime as jest.Mock).mockResolvedValue({ ok: true, status: 'queued', internal_task_id: 'wan3_test', reserve_cost: 60 })
  ;(uploadWan3PrimeReference as jest.Mock).mockImplementation(async (kind, file) => ({
    id: file.name, name: file.name, url: `https://owned.test/${file.name}`, type: kind, size: file.size,
  }))
})
async function upload(label: string, filename: string, mime: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { files: [new File(['synthetic'], filename, { type: mime })] } })
  await waitFor(() => expect(screen.getByText(filename)).toBeInTheDocument())
}

test('edit source, mixed references, false and zero survive quote and explicit start', async () => {
  render(<Wan3PrimeForm credits={1000} />)
  fireEvent.click(screen.getByRole('button', { name: 'Редактирование видео' }))
  await upload('Загрузить исходное видео (Video1)', 'source.mp4', 'video/mp4')
  await upload('Загрузить фото-референсы', 'face.png', 'image/png')
  await upload('Загрузить аудио-референсы', 'voice.mp3', 'audio/mpeg')
  fireEvent.change(screen.getByLabelText('Дополнительный источник'), { target: { value: 'file' } })
  await upload('Загрузить документ', 'brief.pdf', 'application/pdf')
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Изменить одежду, сохранить движения.' } })
  fireEvent.change(screen.getByLabelText('Seed Wan'), { target: { value: '0' } })
  fireEvent.click(screen.getByLabelText('Аудио в результате'))
  fireEvent.change(screen.getByLabelText('Длительность Wan'), { target: { value: '-1' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(quoteWan3Prime).toHaveBeenCalledTimes(1))
  const recipe = (quoteWan3Prime as jest.Mock).mock.calls[0][0].recipe
  expect(recipe).toMatchObject({ scenario: 'edit', duration: -1, audio: false, seed: 0,
    reference_video_urls: ['https://owned.test/source.mp4'], reference_image_urls: ['https://owned.test/face.png'],
    reference_audio_urls: ['https://owned.test/voice.mp3'], reference_file_urls: ['https://owned.test/brief.pdf'],
    reference_link_urls: [], first_frame_url: null, last_frame_url: null })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Запустить Wan' }))
  await screen.findByText('wan3_test')
  expect(generateWan3Prime).toHaveBeenCalledWith(expect.objectContaining({ recipe, quote_hash: 'quote-1', idempotency_key: expect.any(String) }))
})

test('audio-only reference accepts empty instruction and mode drafts preserve media', async () => {
  render(<Wan3PrimeForm credits={1000} />)
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  await upload('Загрузить аудио-референсы', 'sound.mp3', 'audio/mpeg')
  fireEvent.click(screen.getByRole('button', { name: 'Первый и последний кадры' }))
  expect(screen.queryByLabelText('Загрузить аудио-референсы')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  expect(screen.getByText('sound.mp3')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(quoteWan3Prime).toHaveBeenCalled())
  expect((quoteWan3Prime as jest.Mock).mock.calls[0][0].recipe).toMatchObject({ prompt: '', scenario: 'reference', reference_audio_urls: ['https://owned.test/sound.mp3'] })
})

test('settings change invalidates approved quote and network retry retains idempotency', async () => {
  ;(generateWan3Prime as jest.Mock).mockRejectedValueOnce(new TypeError('Network interrupted'))
  render(<Wan3PrimeForm credits={1000} />)
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Рассвет.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Seed Wan'), { target: { value: '0' } })
  expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(quoteWan3Prime).toHaveBeenCalledTimes(2))
  fireEvent.click(screen.getByRole('button', { name: 'Запустить Wan' }))
  await screen.findByRole('button', { name: 'Проверить запуск' })
  fireEvent.click(screen.getByRole('button', { name: 'Проверить запуск' }))
  await waitFor(() => expect(generateWan3Prime).toHaveBeenCalledTimes(2))
  expect((generateWan3Prime as jest.Mock).mock.calls[0][0].idempotency_key).toBe((generateWan3Prime as jest.Mock).mock.calls[1][0].idempotency_key)
})
