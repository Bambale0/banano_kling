import '@testing-library/jest-dom'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { TrendsTab } from '@/components/tabs/trends-tab'
import * as api from '@/lib/api'
import * as wanApi from '@/lib/wan3-prime-api'

const mockState = {
  mode: 'live', user: { isAdmin: true },
  imageModels: [{ id: 'banana_pro', label: 'Banana', ratios: ['1:1'], qualities: ['2K'] }],
  videoModels: ['wan_3', 'wan_3_prime', 'seedance_2'].map(id => ({ id, label: id, supports: ['imgtxt'], ratios: ['16:9'], durations: [5] })),
}
jest.mock('@/lib/app-context', () => ({ useApp: () => ({ state: mockState, trendToRun: null, setTrendToRun: jest.fn() }) }))
jest.mock('@/lib/api', () => ({
  getApiBasePath: () => '/api', getInitData: () => 'signed', getStartParamFallback: () => '',
  fetchPrompts: jest.fn(), submitPrompt: jest.fn(), uploadFile: jest.fn(), deactivatePrompt: jest.fn(), fetchPromptLink: jest.fn(),
}))
jest.mock('@/lib/clipboard', () => ({ copyTextToClipboard: jest.fn() }))
jest.mock('@/lib/seedance-trend-admin-api', () => ({ publishSeedanceTrendUpload: jest.fn() }))
jest.mock('@/components/seedance-trend-upload-references', () => ({ SeedanceTrendUploadReferences: () => null, emptySeedanceUploadReferences: () => ({ images: [], videos: [], audios: [] }) }))
jest.mock('@/lib/trend-admin-api', () => ({ updateTrendPreview: jest.fn() }))
jest.mock('@/lib/media-url', () => ({ normalizeMiniAppMediaUrl: (value: string) => value, mediaAspectRatio: () => '1:1', videoPreviewFrameUrl: () => '' }))
jest.mock('@/lib/trend-price', () => ({ formatTrendRepeatCost: () => '' }))
jest.mock('@/lib/genjutsu-api', () => ({ genjutsuCall: jest.fn().mockResolvedValue({ items: [] }), openGenjutsu: jest.fn() }))
jest.mock('@/components/trend-runner-dialog', () => ({ TrendRunnerDialog: () => null }))
jest.mock('@/components/ui/dialog', () => ({ Dialog: () => null, DialogContent: () => null, DialogTitle: () => null }))
jest.mock('@/lib/wan3-prime-api', () => ({
  ...jest.requireActual('@/lib/wan3-prime-api'),
  quoteWan3Prime: jest.fn(), generateWan3Prime: jest.fn(), uploadWan3PrimeReference: jest.fn(), importWan3PrimeReference: jest.fn(),
}))
const apiMock = api as jest.Mocked<typeof api>
const wanMock = wanApi as jest.Mocked<typeof wanApi>
const file = (name: string, type = 'image/png') => new File(['test'], name, { type })
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej }); return { promise, resolve, reject } }
beforeEach(() => {
  jest.clearAllMocks()
  apiMock.fetchPrompts.mockResolvedValue([])
  apiMock.uploadFile.mockResolvedValue({ url: 'https://owned/preview.jpg' } as any)
  // Keep publishing pending: the outgoing object is asserted before a new catalog render.
  apiMock.submitPrompt.mockImplementation(() => new Promise(() => {}))
  wanMock.uploadWan3PrimeReference.mockImplementation(async (_kind, picked) => ({ url: `https://owned/${picked.name}` } as any))
})
async function openWan(model: 'wan_3' | 'wan_3_prime' = 'wan_3') {
  render(<TrendsTab />)
  fireEvent.click(screen.getByRole('button', { name: 'Добавить', exact: true }))
  // An earlier generic template field must never silently enter WAN settings.
  fireEvent.click(screen.getByRole('button', { name: '+ Имя' }))
  fireEvent.click(screen.getByRole('button', { name: 'Видео-тренд' }))
  fireEvent.change(screen.getByRole('combobox', { name: 'Видео-нейросеть' }), { target: { value: model } })
  await screen.findByLabelText('Инструкции Wan')
  fireEvent.change(screen.getByPlaceholderText('Название тренда'), { target: { value: 'Own WAN trend' } })
  fireEvent.change(screen.getByPlaceholderText('Что получится и какие исходники нужны'), { target: { value: 'Visible description' } })
  fireEvent.change(screen.getByLabelText('Preview тренда'), { target: { files: [file('preview.jpg')] } })
  await waitFor(() => expect(screen.getByAltText('Preview тренда')).toHaveAttribute('src', 'https://owned/preview.jpg'))
}
async function upload(label: string, name: string, type?: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { files: [file(name, type)] } })
  await waitFor(() => expect(screen.queryByText(/Подготавливаю «|Загружаю «/)).not.toBeInTheDocument())
}

test.each(['wan_3', 'wan_3_prime'] as const)('rendered manual editor publishes full owned %s recipe without generation', async model => {
  await openWan(model)
  const select = screen.getByRole('combobox', { name: 'Видео-нейросеть' })
  expect(within(select).getByRole('option', { name: 'Wan 3.0 Video', exact: true })).toHaveValue('wan_3')
  expect(within(select).getByRole('option', { name: 'Wan 3.0 Video Prime' })).toHaveValue('wan_3_prime')
  expect(select).toHaveValue(model)
  expect(screen.queryByRole('button', { name: '+ Имя' })).not.toBeInTheDocument()
  expect(screen.queryByPlaceholderText('Скрытый prompt, который подставится при повторе')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Редактирование видео' }))
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: ' Use Image1, Video1, Video2 and Audio1. ' } })
  fireEvent.change(screen.getByLabelText('Качество Wan'), { target: { value: '720P' } })
  fireEvent.change(screen.getByLabelText('Формат Wan'), { target: { value: '9:16' } })
  fireEvent.change(screen.getByLabelText('Длительность Wan'), { target: { value: '8' } })
  fireEvent.change(screen.getByLabelText('Seed Wan'), { target: { value: '42' } })
  fireEvent.click(screen.getByLabelText('Аудио в результате'))
  fireEvent.click(screen.getByLabelText('Проверка контента'))
  await upload('Загрузить исходное видео (Video1)', 'source.mp4', 'video/mp4')
  await upload('Загрузить видео-референсы', 'extra.mp4', 'video/mp4')
  await upload('Загрузить фото-референсы', 'look.png')
  await upload('Загрузить аудио-референсы', 'voice.mp3', 'audio/mpeg')
  fireEvent.change(screen.getByLabelText('Дополнительный источник'), { target: { value: 'file' } })
  await upload('Загрузить документ', 'script.pdf', 'application/pdf')
  expect(screen.getByLabelText('При повторе: Video1 · исходное видео')).toHaveValue('replaceable')
  fireEvent.change(screen.getByLabelText('При повторе: Image1'), { target: { value: 'fixed' } })
  fireEvent.change(screen.getByLabelText('При повторе: Документ 1'), { target: { value: 'fixed' } })
  const publish = screen.getByRole('button', { name: 'Опубликовать тренд' })
  await waitFor(() => expect(publish).toBeEnabled())
  fireEvent.click(publish)
  expect(apiMock.submitPrompt).toHaveBeenCalledTimes(1)
  const payload = apiMock.submitPrompt.mock.calls[0][0]
  expect(payload).toEqual({
    title: 'Own WAN trend', description: 'Visible description', previewUrl: 'https://owned/preview.jpg',
    model, promptText: 'Use Image1, Video1, Video2 and Audio1.', tags: ['trend', 'trend-video'],
    generationSettings: { kind: 'video', model, preview_type: 'image',
      wan3_recipe: { model, scenario: 'edit', prompt: 'Use Image1, Video1, Video2 and Audio1.', resolution: '720P', aspect_ratio: '9:16', duration: 8,
        audio: false, nsfw_checker: true, seed: 42, first_frame_url: null, last_frame_url: null,
        reference_image_urls: ['https://owned/look.png'], reference_video_urls: ['https://owned/source.mp4', 'https://owned/extra.mp4'],
        reference_audio_urls: ['https://owned/voice.mp3'], reference_file_urls: ['https://owned/script.pdf'], reference_link_urls: [] },
      wan3_replacement_keys: ['video:0', 'video:1', 'audio:0'],
    },
  })
  expect(apiMock.uploadFile).toHaveBeenCalledTimes(1)
  expect(wanMock.uploadWan3PrimeReference.mock.calls.map(call => call[0])).toEqual(['video', 'video', 'image', 'audio', 'file'])
  expect(publish).toBeDisabled()
  fireEvent.click(publish)
  expect(apiMock.submitPrompt).toHaveBeenCalledTimes(1)
  expect(wanMock.quoteWan3Prime).not.toHaveBeenCalled()
  expect(wanMock.generateWan3Prime).not.toHaveBeenCalled()
})

test('numbered first/last frame slots are exact and changing draft mode clears media', async () => {
  await openWan()
  fireEvent.click(screen.getByRole('button', { name: 'Первый и последний кадры' }))
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Animate frames' } })
  await upload('Загрузить первый кадр', 'first.png')
  await upload('Загрузить последний кадр', 'last.png')
  expect(screen.getByLabelText('При повторе: Первый кадр')).toHaveValue('replaceable')
  fireEvent.change(await screen.findByLabelText('При повторе: Последний кадр'), { target: { value: 'fixed' } })
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать тренд' }))
  expect(apiMock.submitPrompt.mock.calls[0][0].generationSettings).toMatchObject({ wan3_replacement_keys: ['first_frame_url'], wan3_recipe: { first_frame_url: 'https://owned/first.png', last_frame_url: 'https://owned/last.png' } })
})

test('pending uploads block publication; model changes and closing abort stale uploads and reset the recipe', async () => {
  await openWan()
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'private old recipe' } })
  const pending = deferred<any>()
  wanMock.uploadWan3PrimeReference.mockImplementationOnce(() => pending.promise)
  fireEvent.change(screen.getByLabelText('Загрузить фото-референсы'), { target: { files: [file('private.png')] } })
  expect(screen.getByRole('button', { name: 'Опубликовать тренд' })).toBeDisabled()
  await waitFor(() => expect(wanMock.uploadWan3PrimeReference).toHaveBeenCalledTimes(1))
  const signal = wanMock.uploadWan3PrimeReference.mock.calls[0][2]!
  fireEvent.change(screen.getByLabelText('Видео-нейросеть'), { target: { value: 'wan_3_prime' } })
  expect(signal.aborted).toBe(true)
  await act(async () => pending.resolve({ url: 'https://owned/private.png' }))
  expect(screen.getByLabelText('Инструкции Wan')).toHaveValue('')
  expect(screen.queryByText('private.png')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  await upload('Загрузить фото-референсы', 'second.png')
  fireEvent.click(screen.getByRole('button', { name: 'По тексту' }))
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  expect(screen.queryByText('second.png')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть', exact: true }))
  fireEvent.click(screen.getByRole('button', { name: 'Добавить', exact: true }))
  expect(screen.getByLabelText('Инструкции Wan')).toHaveValue('')
  expect(screen.getByRole('button', { name: 'По тексту' })).toHaveAttribute('aria-pressed', 'true')
})

test('failed publishing leaves the draft retryable and never displays raw errors', async () => {
  await openWan()
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Keep this prompt' } })
  apiMock.submitPrompt.mockRejectedValueOnce(new Error('provider model secret 123'))
  const publish = screen.getByRole('button', { name: 'Опубликовать тренд' })
  fireEvent.click(publish)
  await screen.findByText('Не удалось опубликовать тренд. Проверьте настройки и файлы, затем повторите.')
  expect(screen.queryByText(/provider|secret/)).not.toBeInTheDocument()
  expect(screen.getByLabelText('Инструкции Wan')).toHaveValue('Keep this prompt')
  expect(publish).toBeEnabled()
  fireEvent.click(publish)
  expect(apiMock.submitPrompt).toHaveBeenCalledTimes(2)
})

test('failed owned upload is safe and retryable; cancelling never adds a reference', async () => {
  await openWan()
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Image1' } })
  wanMock.uploadWan3PrimeReference.mockRejectedValueOnce(new wanApi.Wan3PrimeApiError('private backend detail', 'temporary_unavailable', 503))
  fireEvent.change(screen.getByLabelText('Загрузить фото-референсы'), { target: { files: [file('retry.png')] } })
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить загрузку' }))
  expect(await screen.findByLabelText('При повторе: Image1')).toHaveValue('replaceable')
  expect(screen.queryByText(/private backend detail/)).not.toBeInTheDocument()
  const pending = deferred<any>()
  wanMock.uploadWan3PrimeReference.mockImplementationOnce(() => pending.promise)
  fireEvent.change(screen.getByLabelText('Загрузить фото-референсы'), { target: { files: [file('cancelled.png')] } })
  await waitFor(() => expect(wanMock.uploadWan3PrimeReference).toHaveBeenCalledTimes(3))
  const signal = wanMock.uploadWan3PrimeReference.mock.calls[2][2]!
  fireEvent.click(screen.getByRole('button', { name: 'Отменить загрузку' }))
  expect(signal.aborted).toBe(true)
  await act(async () => pending.reject(new DOMException('Aborted', 'AbortError')))
  expect(screen.queryByLabelText('При повторе: Image2')).not.toBeInTheDocument()
  expect(screen.getAllByRole('alert')[0]).toHaveTextContent('Загрузка отменена. Можно повторить.')
})

test('removing a fixed slot never silently fixes a different file or restores a previous mode grant', async () => {
  await openWan()
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  await upload('Загрузить фото-референсы', 'fixed.png')
  await upload('Загрузить фото-референсы', 'replace.png')
  fireEvent.change(screen.getByLabelText('При повторе: Image1'), { target: { value: 'fixed' } })
  fireEvent.click(screen.getByRole('button', { name: 'Удалить Image1' }))
  expect(screen.getByLabelText('При повторе: Image1')).toHaveValue('replaceable')
  fireEvent.click(screen.getByRole('button', { name: 'По тексту' }))
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  await upload('Загрузить фото-референсы', 'fixed.png')
  expect(await screen.findByLabelText('При повторе: Image1')).toHaveValue('replaceable')
})

test('a stale preview failure cannot restore media or expose raw errors after switching to WAN', async () => {
  const pending = deferred<any>()
  apiMock.uploadFile.mockImplementationOnce(() => pending.promise)
  render(<TrendsTab />)
  fireEvent.click(screen.getByRole('button', { name: 'Добавить', exact: true }))
  fireEvent.change(screen.getByLabelText('Preview тренда'), { target: { files: [file('preview.jpg')] } })
  fireEvent.click(screen.getByRole('button', { name: 'Видео-тренд' }))
  fireEvent.change(screen.getByRole('combobox', { name: 'Видео-нейросеть' }), { target: { value: 'wan_3' } })
  await act(async () => pending.reject(new Error('private provider detail')))
  expect(screen.queryByAltText('Preview тренда')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Опубликовать тренд' })).toBeDisabled()
  expect(screen.queryByText(/private provider detail/)).not.toBeInTheDocument()
})


// An incomplete selection must never be published as a silently reduced recipe.
test.each(['partial batch', 'additional upload'])('%s failure blocks publication across unrelated edits and uploads', async failure => {
  await openWan()
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Use Image1 and Image2' } })
  if (failure === 'additional upload') await upload('Загрузить фото-референсы', 'first.png')
  wanMock.uploadWan3PrimeReference.mockImplementation(async (_kind, picked) => {
    if (picked.name === 'failed.png') throw new Error('private upload details')
    return { url: `https://owned/${picked.name}` } as any
  })
  fireEvent.change(screen.getByLabelText('Загрузить фото-референсы'), { target: {
    files: failure === 'partial batch' ? [file('first.png'), file('failed.png')] : [file('failed.png')],
  } })
  const retry = await screen.findByRole('button', { name: 'Повторить загрузку' })
  const publish = screen.getByRole('button', { name: 'Опубликовать тренд' })
  expect(publish).toBeDisabled()
  expect(screen.getByLabelText('Загрузить фото-референсы')).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'An unrelated instruction edit' } })
  await upload('Загрузить аудио-референсы', 'voice.mp3', 'audio/mpeg')
  expect(publish).toBeDisabled()
  fireEvent.click(publish)
  expect(apiMock.submitPrompt).not.toHaveBeenCalled()
  wanMock.uploadWan3PrimeReference.mockImplementation(async (_kind, picked) => ({ url: `https://owned/${picked.name}` } as any))
  fireEvent.click(retry)
  await waitFor(() => expect(publish).toBeEnabled())
  fireEvent.click(publish)
  expect(apiMock.submitPrompt.mock.calls[0][0].generationSettings?.wan3_recipe?.reference_image_urls).toEqual(['https://owned/first.png', 'https://owned/failed.png'])
  expect(wanMock.generateWan3Prime).not.toHaveBeenCalled()
  expect(wanMock.quoteWan3Prime).not.toHaveBeenCalled()
})

test('explicit discard clears only its failed field; mode reset clears discarded selections', async () => {
  await openWan()
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Use selected references' } })
  await upload('Загрузить фото-референсы', 'first.png')
  wanMock.uploadWan3PrimeReference.mockRejectedValue(new Error('synthetic failure'))
  fireEvent.change(screen.getByLabelText('Загрузить фото-референсы'), { target: { files: [file('second.png')] } })
  await screen.findByRole('button', { name: 'Повторить загрузку' })
  fireEvent.change(screen.getByLabelText('Загрузить аудио-референсы'), { target: { files: [file('voice.mp3', 'audio/mpeg')] } })
  await waitFor(() => expect(screen.getAllByRole('button', { name: 'Повторить загрузку' })).toHaveLength(2))
  const publish = screen.getByRole('button', { name: 'Опубликовать тренд' })
  fireEvent.click(screen.getAllByRole('button', { name: 'Удалить незагруженные файлы' })[0])
  expect(publish).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Удалить незагруженные файлы' }))
  await waitFor(() => expect(publish).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Загрузить фото-референсы'), { target: { files: [file('again.png')] } })
  await screen.findByRole('button', { name: 'Повторить загрузку' })
  fireEvent.click(screen.getByRole('button', { name: 'По тексту' }))
  await waitFor(() => expect(publish).toBeEnabled())
  expect(screen.queryByRole('button', { name: 'Повторить загрузку' })).not.toBeInTheDocument()
})

test.each(['wan_3', 'wan_3_prime'] as const)('%s metadata uses 60/200 limits and blocks retained oversized values', async model => {
  await openWan(model)
  const title = screen.getByPlaceholderText('Название тренда')
  const description = screen.getByPlaceholderText('Что получится и какие исходники нужны')
  const publish = screen.getByRole('button', { name: 'Опубликовать тренд' })
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Animate' } })
  expect(title).toHaveAttribute('maxlength', '60')
  expect(description).toHaveAttribute('maxlength', '200')
  fireEvent.change(title, { target: { value: 'T'.repeat(61) } })
  expect(publish).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('Название тренда Wan — максимум 60 символов.')
  fireEvent.change(title, { target: { value: 'T'.repeat(60) } })
  fireEvent.change(description, { target: { value: 'D'.repeat(201) } })
  expect(publish).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('Описание тренда Wan — максимум 200 символов.')
  fireEvent.change(description, { target: { value: 'D'.repeat(200) } })
  expect(publish).toBeEnabled()
  fireEvent.change(screen.getByRole('combobox', { name: 'Видео-нейросеть' }), { target: { value: 'seedance_2' } })
  expect(title).toHaveAttribute('maxlength', '80')
  expect(description).toHaveAttribute('maxlength', '240')
  fireEvent.change(title, { target: { value: 'T'.repeat(80) } })
  fireEvent.change(description, { target: { value: 'D'.repeat(240) } })
  fireEvent.change(screen.getByRole('combobox', { name: 'Видео-нейросеть' }), { target: { value: model } })
  fireEvent.change(screen.getByLabelText('Инструкции Wan'), { target: { value: 'Animate' } })
  expect(publish).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('Название тренда Wan — максимум 60 символов.')
})

test('WAN publication enforces the exact 64,000 UTF-8 byte budget without truncating the prompt', async () => {
  await openWan()
  const instructions = screen.getByLabelText('Инструкции Wan')
  const publish = screen.getByRole('button', { name: 'Опубликовать тренд' })
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  // Material URL overhead shares the JSON budget with the instruction.
  const ownedUrl = 'https://owned/' + 'a'.repeat(8000) + '.png'
  wanMock.uploadWan3PrimeReference.mockResolvedValueOnce({ url: ownedUrl } as any)
  await upload('Загрузить фото-референсы', 'first.png')
  fireEvent.change(instructions, { target: { value: 'x' } })
  fireEvent.click(publish)
  const serialized = apiMock.submitPrompt.mock.calls[0][0].generationSettings!
  const baseBytes = new Blob([JSON.stringify({ ...serialized, wan3_recipe: { ...serialized.wan3_recipe, prompt: '' } })]).size
  // Reopen after the mocked pending submission to test both exact boundaries.
  cleanup()
  apiMock.submitPrompt.mockClear()
  await openWan()
  fireEvent.click(screen.getByRole('button', { name: 'По референсам' }))
  wanMock.uploadWan3PrimeReference.mockResolvedValueOnce({ url: ownedUrl } as any)
  await upload('Загрузить фото-референсы', 'first.png')
  const input = screen.getByLabelText('Инструкции Wan')
  const button = screen.getByRole('button', { name: 'Опубликовать тренд' })
  const budget = 64_000 - baseBytes
  const exact = '界'.repeat(Math.floor(budget / 3)) + 'x'.repeat(budget % 3)
  expect(Array.from(exact).length).toBeLessThanOrEqual(20000)
  fireEvent.change(input, { target: { value: exact + 'x' } })
  expect(button).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('Рецепт Wan превышает 64 000 байт')
  expect(input).toHaveValue(exact + 'x')
  fireEvent.change(input, { target: { value: exact } })
  expect(button).toBeEnabled()
  fireEvent.click(button)
  const payload = apiMock.submitPrompt.mock.calls[0][0].generationSettings!
  expect(new Blob([JSON.stringify(payload)]).size).toBe(64_000)
  expect(payload.wan3_recipe?.prompt).toBe(exact)
})
