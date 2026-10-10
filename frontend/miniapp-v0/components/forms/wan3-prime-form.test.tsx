import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Wan3PrimeForm } from './wan3-prime-form'
import { fetchWan3PrimeRepeatPlan, generateWan3Prime, quoteWan3Prime, uploadWan3PrimeReference } from '@/lib/wan3-prime-api'

jest.mock('@/lib/wan3-prime-api', () => ({
  quoteWan3Prime: jest.fn(), generateWan3Prime: jest.fn(),
  uploadWan3PrimeReference: jest.fn(), importWan3PrimeReference: jest.fn(),
  fetchWan3PrimeOwnerRecipe: jest.fn(), fetchWan3PrimeRepeatPlan: jest.fn(), fetchWan3PrimeTrendPlan: jest.fn(),
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


test('confirmed provider rejection is shown as failed and refunded, never accepted', async () => {
  ;(generateWan3Prime as jest.Mock).mockResolvedValue({ ok: true, status: 'failed', internal_task_id: 'wan3_failed',
    reserve_cost: 60, charged_cost: 0, refunded_cost: 60 })
  render(<Wan3PrimeForm credits={1000} />)
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Рассвет.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Запустить Wan' }))
  await screen.findByText('wan3_failed')
  expect(screen.queryByText('Видео принято в работу.')).not.toBeInTheDocument()
  expect(screen.getByText(/Генерация не выполнена/)).toBeInTheDocument()
  expect(screen.getByText(/Возвращено: 60/)).toBeInTheDocument()
})


test('shared edit asks only for replacement slots and preserves private Video1 on the server', async () => {
  ;(fetchWan3PrimeRepeatPlan as jest.Mock).mockResolvedValue({ ok: true, source_feed_gen_id: 42, repeat_plan_hash: 'consent-42',
    recipe: { model: 'wan_3_prime', scenario: 'edit', prompt: '', duration: 5, aspect_ratio: '9:16', resolution: '720P', audio: true, nsfw_checker: true },
    slots: [
      { key: 'image:0', kind: 'image', role: 'reference', index: 0, binding: 'upload' },
      { key: 'video:0', kind: 'video', role: 'source_video', index: 0, binding: 'fixed' },
      { key: 'audio:0', kind: 'audio', role: 'reference', index: 0, binding: 'upload' },
    ] })
  render(<Wan3PrimeForm credits={1000} publicationSourceId={42} />)
  await screen.findByLabelText('Загрузить Image1')
  expect(screen.queryByLabelText('Загрузить исходное видео (Video1)')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'По тексту' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  await upload('Загрузить Image1', 'my-face.png', 'image/png')
  await upload('Загрузить Audio1', 'my-sound.mp3', 'audio/mpeg')
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(quoteWan3Prime).toHaveBeenCalledTimes(1))
  const sent = (quoteWan3Prime as jest.Mock).mock.calls[0][0].recipe
  expect(sent).toMatchObject({ scenario: 'edit', prompt: '', source_feed_gen_id: 42, repeat_plan_hash: 'consent-42',
    repeat_replacements: { 'image:0': 'https://owned.test/my-face.png', 'audio:0': 'https://owned.test/my-sound.mp3' },
    reference_video_urls: [] })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Запустить Wan' }))
  await screen.findByText('wan3_test')
  expect((generateWan3Prime as jest.Mock).mock.calls[0][0].recipe).toEqual(sent)
})

test('restoring an owned derived recipe retains its output settings after consent reload', async () => {
  const api = jest.requireMock('@/lib/wan3-prime-api')
  api.fetchWan3PrimeOwnerRecipe.mockResolvedValue({ ok: true, recipe: {
    model: 'wan_3_prime', scenario: 'edit', source_feed_gen_id: 123, prompt: 'Keep my changes',
    resolution: '480P', aspect_ratio: '4:3', duration: 7, audio: false, seed: 0, nsfw_checker: true,
    repeat_plan_hash: 'old', repeat_replacements: { 'image:0': 'https://owned.test/mine.png' },
  } })
  api.fetchWan3PrimeRepeatPlan.mockResolvedValue({ ok: true, source_feed_gen_id: 123, repeat_plan_hash: 'fresh',
    recipe: { model: 'wan_3_prime', scenario: 'edit', prompt: '', resolution: '1080P',
      aspect_ratio: 'adaptive', duration: 5, audio: true, seed: 123, nsfw_checker: false },
    slots: [{ key: 'image:0', kind: 'image', role: 'reference', index: 0, binding: 'upload' }],
  })
  render(<Wan3PrimeForm credits={1000} ownerTaskId="wan3_owned_repeat" />)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(quoteWan3Prime).toHaveBeenCalled())
  expect((quoteWan3Prime as jest.Mock).mock.calls[0][0].recipe).toMatchObject({ resolution: '480P',
    aspect_ratio: '4:3', duration: 7, audio: false, seed: 0, nsfw_checker: true,
    prompt: 'Keep my changes', repeat_plan_hash: 'fresh' })
})

test('owner recipe restoration reveals its saved document and submits it visibly', async () => {
  const api = jest.requireMock('@/lib/wan3-prime-api')
  api.fetchWan3PrimeOwnerRecipe.mockResolvedValue({ ok: true, recipe: {
    model: 'wan_3_prime', scenario: 'reference', prompt: 'Use the brief',
    resolution: '720P', aspect_ratio: 'adaptive', duration: 5, audio: true, nsfw_checker: true,
    reference_file_urls: ['https://owned.test/saved-brief.pdf'], reference_link_urls: [],
  } })
  render(<Wan3PrimeForm credits={1000} ownerTaskId="wan3_owned_document" />)
  const selector = await screen.findByRole('combobox', { name: 'Дополнительный источник' })
  await waitFor(() => expect(selector).toHaveValue('file'))
  expect(screen.getByText('saved-brief.pdf')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Удалить Файл 1' }))
  expect(screen.queryByText('saved-brief.pdf')).not.toBeInTheDocument()
  await upload('Загрузить документ', 'replacement.pdf', 'application/pdf')
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(quoteWan3Prime).toHaveBeenCalledTimes(1))
  expect((quoteWan3Prime as jest.Mock).mock.calls[0][0].recipe).toMatchObject({
    reference_file_urls: ['https://owned.test/replacement.pdf'], reference_link_urls: [],
  })
})

test('repeated initial recipe restoration switches the visible optional source and quote payload', async () => {
  const base = {
    model: 'wan_3_prime' as const, scenario: 'reference' as const, prompt: 'Use the source',
    resolution: '720P' as const, aspect_ratio: 'adaptive' as const, duration: 5,
    audio: true, nsfw_checker: true,
  }
  const { rerender } = render(<Wan3PrimeForm credits={1000} initialRecipe={{
    ...base, reference_link_urls: ['https://example.test/saved-page'], reference_file_urls: [],
  }} />)
  const selector = screen.getByRole('combobox', { name: 'Дополнительный источник' })
  expect(selector).toHaveValue('link')
  expect(screen.getByText('saved-page')).toBeInTheDocument()
  rerender(<Wan3PrimeForm credits={1000} initialRecipe={{
    ...base, reference_link_urls: [], reference_file_urls: ['https://owned.test/replacement.pdf'],
  }} />)
  await waitFor(() => expect(selector).toHaveValue('file'))
  expect(screen.getByText('replacement.pdf')).toBeInTheDocument()
  expect(screen.queryByText('saved-page')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(quoteWan3Prime).toHaveBeenCalledTimes(1))
  expect((quoteWan3Prime as jest.Mock).mock.calls[0][0].recipe).toMatchObject({
    reference_file_urls: ['https://owned.test/replacement.pdf'], reference_link_urls: [],
  })
})
