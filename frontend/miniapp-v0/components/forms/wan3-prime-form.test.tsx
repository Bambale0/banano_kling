import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Wan3PrimeForm } from './wan3-prime-form'
import { fetchWan3PrimeRepeatPlan, generateWan3Prime, importWan3PrimeReference, quoteWan3Prime, uploadWan3PrimeReference } from '@/lib/wan3-prime-api'

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

test('duration uses a seconds slider and a separate Auto switch that restores manual seconds', async () => {
  render(<Wan3PrimeForm credits={1000} />)
  const slider = screen.getByRole('slider', { name: 'Длительность Wan' })
  const automatic = screen.getByRole('switch', { name: 'Auto: длительность Wan' })
  expect(slider).toHaveValue('5')
  expect(slider).toHaveAttribute('min', '2')
  expect(slider).toHaveAttribute('max', '30')
  expect(slider).toHaveAttribute('step', '1')
  expect(screen.getByText('5 сек')).toBeInTheDocument()
  fireEvent.change(slider, { target: { value: '12' } })
  expect(slider).toHaveAttribute('aria-valuetext', '12 секунд')
  expect(screen.getByText('12 сек')).toBeInTheDocument()
  fireEvent.click(automatic)
  expect(automatic).toBeChecked()
  expect(slider).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Рассвет.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(quoteWan3Prime).toHaveBeenCalledTimes(1))
  expect((quoteWan3Prime as jest.Mock).mock.calls[0][0].recipe.duration).toBe(-1)
  fireEvent.click(automatic)
  expect(slider).toBeEnabled()
  expect(slider).toHaveValue('12')
  expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeDisabled()
})

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
  fireEvent.click(screen.getByRole('switch', { name: 'Auto: длительность Wan' }))
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

test('manual slider endpoints invalidate quotes and unknown source duration remains server-validated', async () => {
  render(<Wan3PrimeForm credits={1000} />)
  fireEvent.click(screen.getByRole('button', { name: 'Редактирование видео' }))
  await upload('Загрузить исходное видео (Video1)', 'Видео.mov', 'video/quicktime')
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Сохранить движения.' } })
  const slider = screen.getByRole('slider', { name: 'Длительность Wan' })
  expect(slider).toHaveAttribute('max', '30')
  fireEvent.change(slider, { target: { value: '2' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeEnabled())
  expect((quoteWan3Prime as jest.Mock).mock.calls[0][0].recipe.duration).toBe(2)
  fireEvent.change(slider, { target: { value: '30' } })
  expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeDisabled()
  ;(quoteWan3Prime as jest.Mock).mockRejectedValueOnce(new Error('Видеореференсы + результат: не более 30 секунд.'))
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await screen.findByRole('alert')
  expect((quoteWan3Prime as jest.Mock).mock.calls[1][0].recipe.duration).toBe(30)
  expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeDisabled()
  expect(generateWan3Prime).not.toHaveBeenCalled()
})

test('restored Auto and manual durations remain reviewable and failed-start retries lock both controls', async () => {
  const base = { model: 'wan_3_prime' as const, scenario: 'text' as const, prompt: 'Рассвет.',
    resolution: '720P' as const, aspect_ratio: 'adaptive' as const, audio: true, nsfw_checker: false }
  const { rerender } = render(<Wan3PrimeForm credits={1000} initialRecipe={{ ...base, duration: -1 }} />)
  const slider = screen.getByRole('slider', { name: 'Длительность Wan' })
  const automatic = screen.getByRole('switch', { name: 'Auto: длительность Wan' })
  expect(automatic).toBeChecked()
  expect(slider).toBeDisabled()
  rerender(<Wan3PrimeForm credits={1000} initialRecipe={{ ...base, duration: 7 }} />)
  expect(automatic).not.toBeChecked()
  expect(slider).toHaveValue('7')
  fireEvent.click(automatic); fireEvent.click(automatic)
  expect(slider).toHaveValue('7')
  ;(generateWan3Prime as jest.Mock).mockRejectedValueOnce(new TypeError('Network interrupted'))
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Запустить Wan' }))
  await screen.findByRole('button', { name: 'Проверить запуск' })
  expect(slider).toBeDisabled()
  expect(automatic).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Проверить запуск' }))
  await screen.findByText('wan3_test')
  expect((generateWan3Prime as jest.Mock).mock.calls[1][0]).toEqual((generateWan3Prime as jest.Mock).mock.calls[0][0])
  fireEvent.click(screen.getByRole('button', { name: 'Новая генерация с этими настройками' }))
  expect(slider).toBeEnabled()
  expect(slider).toHaveValue('7')
})

test('photo failure and retry stay visible beside the input with the original Cyrillic filename', async () => {
  ;(uploadWan3PrimeReference as jest.Mock).mockRejectedValueOnce(new Error('Не удалось загрузить часть файла.'))
    .mockResolvedValueOnce({ url: 'https://owned.test/upload.jpg', name: 'upload.jpg', type: 'image', size: 9 })
  render(<Wan3PrimeForm credits={1000} />)
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  const field = within(screen.getByRole('region', { name: 'Фото-референсы' }))
  fireEvent.change(field.getByLabelText('Загрузить фото-референсы'), { target: { files: [new File(['synthetic'], 'Фото.jpg', { type: 'image/jpeg' })] } })
  expect(field.getByRole('status')).toHaveTextContent('Фото.jpg')
  expect(await field.findByRole('alert')).toHaveTextContent('Фото.jpg')
  expect(field.getByRole('alert')).toHaveTextContent('Не удалось загрузить часть файла.')
  fireEvent.click(field.getByRole('button', { name: 'Повторить загрузку' }))
  await field.findByText('Фото.jpg')
  expect(field.queryByRole('alert')).not.toBeInTheDocument()
  expect(field.queryByRole('status')).not.toBeInTheDocument()
  expect(uploadWan3PrimeReference).toHaveBeenCalledTimes(2)
  expect((uploadWan3PrimeReference as jest.Mock).mock.calls[1][1].name).toBe('Фото.jpg')
})

test('multi-file retry uploads only the unfinished files, preserving the accepted video once', async () => {
  ;(uploadWan3PrimeReference as jest.Mock)
    .mockResolvedValueOnce({ url: 'https://owned.test/one.mov' })
    .mockRejectedValueOnce(new Error('Сеть недоступна.'))
    .mockResolvedValueOnce({ url: 'https://owned.test/two.mov' })
  render(<Wan3PrimeForm credits={1000} />)
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  const field = within(screen.getByRole('region', { name: 'Видео-референсы' }))
  fireEvent.change(field.getByLabelText('Загрузить видео-референсы'), { target: { files: [
    new File(['one'], 'Видео.mov', { type: 'video/quicktime' }), new File(['two'], 'Следующее.mov', { type: 'video/quicktime' }),
  ] } })
  await field.findByRole('alert')
  expect(field.getAllByText('Видео.mov')).toHaveLength(1)
  fireEvent.click(field.getByRole('button', { name: 'Повторить загрузку' }))
  await field.findByText('Следующее.mov')
  expect(field.getAllByText('Видео.mov')).toHaveLength(1)
  expect((uploadWan3PrimeReference as jest.Mock).mock.calls.map(call => call[1].name)).toEqual(['Видео.mov', 'Следующее.mov', 'Следующее.mov'])
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(quoteWan3Prime).toHaveBeenCalledTimes(1))
  expect((quoteWan3Prime as jest.Mock).mock.calls[0][0].recipe.reference_video_urls).toEqual(['https://owned.test/one.mov', 'https://owned.test/two.mov'])
})

test('busy upload rejects repeated selections and cancel unlocks a retry without adding late media', async () => {
  let finish: (result: unknown) => void = () => {}
  let signal: AbortSignal | undefined
  ;(uploadWan3PrimeReference as jest.Mock).mockImplementationOnce((_kind, _file, currentSignal, progress) => {
    signal = currentSignal
    progress(5, 10)
    return new Promise((resolve, reject) => { finish = resolve; currentSignal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }) })
  })
  render(<Wan3PrimeForm credits={1000} />)
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  const field = within(screen.getByRole('region', { name: 'Фото-референсы' }))
  const input = field.getByLabelText('Загрузить фото-референсы')
  const change = { target: { files: [new File(['synthetic'], 'Фото.jpg', { type: 'image/jpeg' })] } }
  fireEvent.change(input, change); fireEvent.change(input, change)
  expect(uploadWan3PrimeReference).toHaveBeenCalledTimes(1)
  expect(field.getByRole('status')).toHaveTextContent('50%')
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  expect(screen.getByRole('slider', { name: 'Длительность Wan' })).toBeDisabled()
  fireEvent.click(field.getByRole('button', { name: 'Отменить загрузку' }))
  await field.findByRole('alert')
  expect(signal?.aborted).toBe(true)
  expect(input).toBeEnabled()
  await act(async () => finish({ url: 'https://owned.test/late.jpg' }))
  expect(field.queryByText('Фото.jpg')).not.toBeInTheDocument()
  expect(field.getByRole('button', { name: 'Повторить загрузку' })).toBeEnabled()
})

test.each([false, true])('recipe replacement (equal content: %s) and unmount discard late uploads', async equalContent => {
  let finish: (result: unknown) => void = () => {}
  let signal: AbortSignal | undefined
  ;(uploadWan3PrimeReference as jest.Mock).mockImplementation((_kind, _file, currentSignal) => {
    signal = currentSignal
    return new Promise(resolve => { finish = resolve })
  })
  const base = { model: 'wan_3_prime' as const, scenario: 'reference' as const, prompt: '', duration: 5,
    resolution: '720P' as const, aspect_ratio: 'adaptive' as const, audio: true, nsfw_checker: false }
  const originalRecipe = { ...base, reference_image_urls: ['https://owned.test/new.jpg'] }
  const { rerender, unmount } = render(<Wan3PrimeForm credits={1000} initialRecipe={originalRecipe} />)
  const change = { target: { files: [new File(['synthetic'], 'Старое.jpg', { type: 'image/jpeg' })] } }
  fireEvent.change(screen.getByLabelText('Загрузить фото-референсы'), change)
  const nextRecipe = equalContent ? { ...originalRecipe } : { ...originalRecipe, prompt: 'Новая инструкция' }
  rerender(<Wan3PrimeForm credits={1000} initialRecipe={nextRecipe} />)
  expect(signal?.aborted).toBe(true)
  await act(async () => finish({ url: 'https://owned.test/old.jpg' }))
  expect(screen.getByText('new.jpg')).toBeInTheDocument()
  expect(screen.queryByText('Старое.jpg')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Загрузить фото-референсы'), change)
  expect(signal?.aborted).toBe(false)
  unmount()
  expect(signal?.aborted).toBe(true)
  await act(async () => finish({ url: 'https://owned.test/old-again.jpg' }))
})

test('link import failure stays local and preserves the address for an explicit retry', async () => {
  ;(importWan3PrimeReference as jest.Mock).mockRejectedValueOnce(new Error('Сервер не ответил за 15 минут.'))
    .mockResolvedValueOnce({ url: 'https://example.test/brief', filename: 'brief' })
  render(<Wan3PrimeForm credits={1000} />)
  fireEvent.click(screen.getByRole('button', { name: 'Из веб-страницы' }))
  const field = within(screen.getByRole('region', { name: 'Веб-страница' }))
  const input = field.getByLabelText('Ссылка: Веб-страница')
  fireEvent.change(input, { target: { value: 'https://example.test/brief' } })
  fireEvent.click(field.getByRole('button', { name: 'Добавить', hidden: true }))
  expect(field.getByRole('status')).toHaveTextContent('Проверяю и импортирую ссылку')
  await field.findByRole('alert')
  expect(input).toHaveValue('https://example.test/brief')
  fireEvent.click(field.getByRole('button', { name: 'Добавить', hidden: true }))
  await field.findByText('brief')
  expect(field.queryByRole('alert')).not.toBeInTheDocument()
  expect(input).toHaveValue('')
})

test('mode change clears unfinished upload retry state from the previous draft', async () => {
  ;(uploadWan3PrimeReference as jest.Mock).mockRejectedValueOnce(new Error('Сеть недоступна.'))
  render(<Wan3PrimeForm credits={1000} />)
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  const field = within(screen.getByRole('region', { name: 'Фото-референсы' }))
  fireEvent.change(field.getByLabelText('Загрузить фото-референсы'), { target: { files: [new File(['synthetic'], 'Фото.jpg', { type: 'image/jpeg' })] } })
  await field.findByRole('alert')
  expect(field.getByRole('button', { name: 'Повторить загрузку' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Из документа' }))
  expect(within(screen.getByRole('region', { name: 'Фото-референсы' })).queryByRole('button', { name: 'Повторить загрузку' })).not.toBeInTheDocument()
})

test('cancellation stays busy until cleanup finishes and retains a cleanup failure for safe retry', async () => {
  let rejectCleanup: (error: Error) => void = () => {}
  let uploadSignal: AbortSignal | undefined
  ;(uploadWan3PrimeReference as jest.Mock).mockImplementationOnce((_kind, _file, signal) => {
    uploadSignal = signal
    return new Promise((_resolve, reject) => { rejectCleanup = reject })
  })
  render(<Wan3PrimeForm credits={1000} />)
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  const field = within(screen.getByRole('region', { name: 'Фото-референсы' }))
  const input = field.getByLabelText('Загрузить фото-референсы')
  fireEvent.change(input, { target: { files: [new File(['synthetic'], 'Фото.jpg', { type: 'image/jpeg' })] } })
  fireEvent.click(field.getByRole('button', { name: 'Отменить загрузку' }))
  expect(uploadSignal?.aborted).toBe(true)
  expect(field.getByRole('status')).toHaveTextContent('Отменяю загрузку')
  expect(field.getByRole('button', { name: 'Отменить загрузку' })).toBeDisabled()
  expect(input).toBeDisabled()
  expect(field.queryByRole('button', { name: 'Повторить загрузку' })).not.toBeInTheDocument()
  await act(async () => rejectCleanup(Object.assign(new Error('Не удалось подтвердить отмену предыдущей загрузки. Повтор сначала проверит и освободит её.'), { name: 'Wan3PrimeUploadCleanupError' })))
  expect(field.getByRole('alert')).toHaveTextContent('Не удалось подтвердить отмену')
  expect(field.getByRole('alert')).not.toHaveTextContent('Загрузка отменена. Можно повторить.')
  expect(field.getByRole('button', { name: 'Повторить загрузку' })).toBeEnabled()
  expect(uploadWan3PrimeReference).toHaveBeenCalledTimes(1)
})


test('ordinary WAN keeps identity across modes and auto-refreshes fixed input-plus-output quote before explicit launch', async () => {
  ;(quoteWan3Prime as jest.Mock).mockImplementation(async ({ recipe }) => ({
    ...quote, auto_duration: false, source_video_duration_seconds: 7,
    billing_duration_seconds: 7 + recipe.duration,
    reserve_cost: 4 * (7 + recipe.duration), quote_hash: 'fixed-' + recipe.duration,
    settlement_notice: 'Показанная стоимость фиксируется при запуске.',
  }))
  render(<Wan3PrimeForm model="wan_3" credits={1000} />)
  expect(screen.getByText('Wan 3.0 Video')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  await upload('Загрузить видео-референсы', 'reference.mp4', 'video/mp4')
  await screen.findByText('Стоимость: 48🍌')
  expect(quoteWan3Prime).toHaveBeenLastCalledWith(expect.objectContaining({
    recipe: expect.objectContaining({ model: 'wan_3', duration: 5 }),
  }), expect.any(AbortSignal))
  expect(generateWan3Prime).not.toHaveBeenCalled()
  fireEvent.change(screen.getByRole('slider', { name: 'Длительность Wan' }), { target: { value: '6' } })
  expect(screen.getByRole('button', { name: 'Запустить Wan' })).toBeDisabled()
  await screen.findByText('Стоимость: 52🍌')
  expect(generateWan3Prime).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Запустить Wan' }))
  await waitFor(() => expect(generateWan3Prime).toHaveBeenCalledWith(expect.objectContaining({
    recipe: expect.objectContaining({ model: 'wan_3', duration: 6 }), quote_hash: 'fixed-6',
  })))
})
