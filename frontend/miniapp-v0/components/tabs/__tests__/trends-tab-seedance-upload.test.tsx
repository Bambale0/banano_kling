import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { TrendsTab } from '@/components/tabs/trends-tab'
import { useApp } from '@/lib/app-context'
import { fetchPrompts, submitPrompt, uploadFile } from '@/lib/api'
import { publishSeedanceTrendUpload } from '@/lib/seedance-trend-admin-api'
import { uploadSeedance25Video } from '@/lib/seedance25-api'
import { genjutsuCall } from '@/lib/genjutsu-api'

jest.mock('@/lib/seedance25-api', () => ({ uploadSeedance25Video: jest.fn() }))
jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({ fetchPrompts: jest.fn(), fetchPromptLink: jest.fn(), deactivatePrompt: jest.fn(), submitPrompt: jest.fn(), uploadFile: jest.fn() }))
jest.mock('@/lib/seedance-trend-admin-api', () => ({ publishSeedanceTrendUpload: jest.fn() }))
jest.mock('@/lib/trend-admin-api', () => ({ updateTrendPreview: jest.fn() }))
jest.mock('@/lib/genjutsu-api', () => ({ genjutsuCall: jest.fn(), openGenjutsu: jest.fn() }))
jest.mock('@/components/trend-runner-dialog', () => ({ TrendRunnerDialog: () => null }))

const mockedUpload = jest.mocked(uploadFile)
const mockedPublish = jest.mocked(publishSeedanceTrendUpload)
const image = (name: string) => new File(['image'], name, { type: 'image/jpeg' })
const uploaded = (file: File) => ({ id: file.name, name: file.name, url: `https://media.example/${file.name}`, type: file.type.split('/')[0], size: file.size })

async function openSeedance(model = 'seedance_2') {
  render(<TrendsTab />)
  fireEvent.click(screen.getByRole('button', { name: 'Добавить' }))
  fireEvent.click(screen.getByRole('button', { name: 'Видео-тренд' }))
  fireEvent.change(screen.getByLabelText('Видео-нейросеть'), { target: { value: model } })
  await screen.findByText('Референсы шаблона')
}

async function addFiles(label: string, files: File[]) {
  fireEvent.change(screen.getByLabelText(label), { target: { files } })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Опубликовать тренд' })).not.toBeDisabled())
}

beforeEach(() => {
  jest.clearAllMocks()
  URL.createObjectURL = jest.fn(() => 'blob:preview')
  URL.revokeObjectURL = jest.fn()
  jest.mocked(useApp).mockReturnValue({
    state: { mode: 'live', user: { isAdmin: true },
      imageModels: [{ id: 'banana_pro', label: 'Banana', ratios: ['1:1'] }],
      videoModels: ['seedance_2', 'seedance_2_5', 'v3_pro'].map((id) => ({ id, label: id, supports: ['imgtxt'], max_image_references: 2, max_video_references: 2, max_audio_references: 1, durations: id === 'seedance_2_5' ? [-1, 5, 10] : [5, 10], ratios: ['16:9', '9:16'] })),
    }, trendToRun: null, setTrendToRun: jest.fn(),
  } as unknown as ReturnType<typeof useApp>)
  jest.mocked(fetchPrompts).mockResolvedValue([])
  jest.mocked(genjutsuCall).mockResolvedValue({ items: [] } as never)
  jest.mocked(uploadSeedance25Video).mockImplementation(async (file) => uploaded(file) as Awaited<ReturnType<typeof uploadFile>>)
  mockedUpload.mockImplementation(async (_kind, file) => uploaded(file) as Awaited<ReturnType<typeof uploadFile>>)
  mockedPublish.mockResolvedValue({ id: 55, title: 'Own refs', tags: ['trend', 'trend-video'], model: 'seedance_2', category: 'video' } as Awaited<ReturnType<typeof publishSeedanceTrendUpload>>)
})

it('publishes own hidden multimodal references separately from the public preview', async () => {
  await openSeedance()
  fireEvent.change(screen.getByPlaceholderText('Название тренда'), { target: { value: 'Own refs' } })
  fireEvent.change(screen.getByPlaceholderText('Скрытый prompt, который подставится при повторе'), { target: { value: 'Use @Image1 and @Image2 with @Video1; age {Возраст}' } })
  fireEvent.click(screen.getByRole('button', { name: '+ Возраст' }))
  await addFiles('Фото-референсы тренда', [image('face.jpg'), image('scene.jpg')])
  await addFiles('Видео-референсы тренда', [new File(['video'], 'motion.mp4', { type: 'video/mp4' })])
  await addFiles('Аудио-референсы тренда', [new File(['audio'], 'music.mp3', { type: 'audio/mpeg' })])
  fireEvent.change(screen.getByLabelText('Режим @Image2'), { target: { value: 'replaceable' } })
  fireEvent.change(screen.getByLabelText('Режим @Audio1'), { target: { value: 'excluded' } })
  await addFiles('Preview тренда', [image('public.jpg')])
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать тренд' }))
  await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
  expect(mockedPublish).toHaveBeenCalledWith(expect.objectContaining({
    model: 'seedance_2', title: 'Own refs', previewUrl: 'https://media.example/public.jpg', previewType: 'image',
    imageUrls: ['https://media.example/face.jpg', 'https://media.example/scene.jpg'],
    videoUrls: ['https://media.example/motion.mp4'], audioUrls: ['https://media.example/music.mp3'],
    identityImageIndex: 1, fixedImageIndices: [], replaceableImageIndices: [2],
    fixedVideoIndices: [1], replaceableVideoIndices: [], fixedAudioIndices: [], replaceableAudioIndices: [],
    userFields: [expect.objectContaining({ key: 'Возраст', type: 'number' })],
    duration: 5, aspectRatio: '16:9',
  }))
  expect(submitPrompt).not.toHaveBeenCalled()
})

it.each(['seedance_2_5', 'v3_pro'])('discards late uploads when switching to %s and does not upload the rest of a stale batch', async (nextModel) => {
  await openSeedance()
  let finish!: (value: Awaited<ReturnType<typeof uploadFile>>) => void
  mockedUpload.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
  fireEvent.change(screen.getByLabelText('Фото-референсы тренда'), { target: { files: [image('late.jpg'), image('never.jpg')] } })
  expect(screen.getByRole('button', { name: 'Опубликовать тренд' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Видео-нейросеть'), { target: { value: nextModel } })
  await act(async () => finish(uploaded(image('late.jpg')) as Awaited<ReturnType<typeof uploadFile>>))
  fireEvent.change(screen.getByLabelText('Видео-нейросеть'), { target: { value: 'seedance_2' } })
  expect(screen.queryByAltText('Исходный @Image1')).not.toBeInTheDocument()
  expect(mockedUpload).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Опубликовать тренд' })).not.toBeDisabled()
})

it('cancels the form without resurrecting late reference or preview uploads after reopening', async () => {
  await openSeedance()
  let finishReference!: (value: Awaited<ReturnType<typeof uploadFile>>) => void
  let finishPreview!: (value: Awaited<ReturnType<typeof uploadFile>>) => void
  mockedUpload.mockImplementationOnce(() => new Promise((resolve) => { finishReference = resolve }))
  mockedUpload.mockImplementationOnce(() => new Promise((resolve) => { finishPreview = resolve }))
  fireEvent.change(screen.getByLabelText('Фото-референсы тренда'), { target: { files: [image('late-face.jpg')] } })
  fireEvent.change(screen.getByLabelText('Preview тренда'), { target: { files: [image('late-cover.jpg')] } })
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
  await act(async () => {
    finishReference(uploaded(image('late-face.jpg')) as Awaited<ReturnType<typeof uploadFile>>)
    finishPreview(uploaded(image('late-cover.jpg')) as Awaited<ReturnType<typeof uploadFile>>)
  })
  fireEvent.click(screen.getByRole('button', { name: 'Добавить' }))
  fireEvent.click(screen.getByRole('button', { name: 'Видео-тренд' }))
  expect(screen.queryByAltText('Исходный @Image1')).not.toBeInTheDocument()
  expect(screen.queryByAltText('Preview тренда')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Опубликовать тренд' })).not.toBeDisabled()
})

it('clears own refs on trend-kind change and hides uploads for other models', async () => {
  await openSeedance()
  await addFiles('Фото-референсы тренда', [image('face.jpg'), image('scene.jpg')])
  fireEvent.click(screen.getByRole('button', { name: 'Фото-тренд' }))
  expect(screen.queryByRole('region', { name: 'Референсы шаблона' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Видео-тренд' }))
  expect(screen.queryByAltText('Исходный @Image1')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Видео-нейросеть'), { target: { value: 'v3_pro' } })
  expect(screen.queryByRole('region', { name: 'Референсы шаблона' })).not.toBeInTheDocument()
})

it.each(['seedance_2', 'seedance_2_5'])('publishes %s with just one replaceable identity photo', async (model) => {
  await openSeedance(model)
  fireEvent.change(screen.getByPlaceholderText('Название тренда'), { target: { value: 'One photo' } })
  fireEvent.change(screen.getByPlaceholderText('Скрытый prompt, который подставится при повторе'), { target: { value: 'Animate @Image1' } })
  await addFiles('Preview тренда', [image('public.jpg')])
  await addFiles('Фото-референсы тренда', [image('face.jpg')])
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать тренд' }))
  await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
  expect(mockedPublish).toHaveBeenCalledWith(expect.objectContaining({
    model, title: 'One photo', promptText: 'Animate @Image1',
    previewUrl: 'https://media.example/public.jpg',
    imageUrls: ['https://media.example/face.jpg'], videoUrls: [], audioUrls: [],
    identityImageIndex: 1, fixedImageIndices: [], replaceableImageIndices: [],
    fixedVideoIndices: [], replaceableVideoIndices: [], fixedAudioIndices: [], replaceableAudioIndices: [],
  }))
  expect(submitPrompt).not.toHaveBeenCalled()
})

it.each(['seedance_2', 'seedance_2_5'])('publishes %s with only identity included when all other media are excluded', async (model) => {
  await openSeedance(model)
  fireEvent.change(screen.getByPlaceholderText('Название тренда'), { target: { value: 'One included photo' } })
  fireEvent.change(screen.getByPlaceholderText('Скрытый prompt, который подставится при повторе'), { target: { value: 'Animate @Image1' } })
  await addFiles('Preview тренда', [image('public.jpg')])
  await addFiles('Фото-референсы тренда', [image('face.jpg'), image('excluded.jpg')])
  await addFiles('Видео-референсы тренда', [new File(['video'], 'excluded.mp4', { type: 'video/mp4' })])
  await addFiles('Аудио-референсы тренда', [new File(['audio'], 'excluded.mp3', { type: 'audio/mpeg' })])
  for (const token of ['Image2', 'Video1', 'Audio1']) {
    fireEvent.change(screen.getByLabelText(`Режим @${token}`), { target: { value: 'excluded' } })
  }
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать тренд' }))
  await waitFor(() => expect(mockedPublish).toHaveBeenCalledTimes(1))
  expect(mockedPublish).toHaveBeenCalledWith(expect.objectContaining({
    model, identityImageIndex: 1,
    fixedImageIndices: [], replaceableImageIndices: [],
    fixedVideoIndices: [], replaceableVideoIndices: [], fixedAudioIndices: [], replaceableAudioIndices: [],
  }))
  expect(submitPrompt).not.toHaveBeenCalled()
})

it.each([
  ['seedance_2', 'fixed'], ['seedance_2', 'excluded'],
  ['seedance_2_5', 'fixed'], ['seedance_2_5', 'excluded'],
])('requires an identity photo for %s with a %s video reference', async (model, mode) => {
  await openSeedance(model)
  fireEvent.change(screen.getByPlaceholderText('Название тренда'), { target: { value: 'Missing identity' } })
  fireEvent.change(screen.getByPlaceholderText('Скрытый prompt, который подставится при повторе'), { target: { value: 'Animate the user photo' } })
  await addFiles('Preview тренда', [image('public.jpg')])
  await addFiles('Видео-референсы тренда', [new File(['video'], 'motion.mp4', { type: 'video/mp4' })])
  fireEvent.change(screen.getByLabelText('Режим @Video1'), { target: { value: mode } })
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать тренд' }))
  expect(await screen.findByText(/Для шаблона выберите фото для замены лица/)).toBeInTheDocument()
  expect(mockedPublish).not.toHaveBeenCalled()
  expect(submitPrompt).not.toHaveBeenCalled()
})

it('locks edits and duplicate submits during publication and preserves references after a server error', async () => {
  await openSeedance('seedance_2_5')
  fireEvent.change(screen.getByPlaceholderText('Название тренда'), { target: { value: 'Own refs' } })
  fireEvent.change(screen.getByPlaceholderText('Скрытый prompt, который подставится при повторе'), { target: { value: 'Use @Image1 and @Image2' } })
  await addFiles('Фото-референсы тренда', [image('face.jpg'), image('scene.jpg')])
  await addFiles('Preview тренда', [image('public.jpg')])
  let rejectPublish!: (error: Error) => void
  mockedPublish.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectPublish = reject }))
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать тренд' }))
  expect(screen.getByRole('button', { name: 'Закрыть' })).toBeDisabled()
  expect(screen.getByLabelText('Видео-нейросеть')).toBeDisabled()
  expect(screen.getByLabelText('Режим @Image2')).toBeDisabled()
  expect(screen.getByPlaceholderText('Название тренда')).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать тренд' }))
  expect(mockedPublish).toHaveBeenCalledTimes(1)
  await act(async () => rejectPublish(new Error('Файл недоступен, загрузите заново')))
  expect(screen.getByText('Файл недоступен, загрузите заново')).toBeInTheDocument()
  expect(screen.getByAltText('Исходный @Image2')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Опубликовать тренд' })).not.toBeDisabled()
})

it('keeps generic Seedance publication when no own references were added', async () => {
  await openSeedance()
  jest.mocked(submitPrompt).mockResolvedValue({ id: 56, title: 'Simple', tags: ['trend'], model: 'seedance_2' } as Awaited<ReturnType<typeof submitPrompt>>)
  fireEvent.change(screen.getByPlaceholderText('Название тренда'), { target: { value: 'Simple' } })
  fireEvent.change(screen.getByPlaceholderText('Скрытый prompt, который подставится при повторе'), { target: { value: 'Animate the user photo' } })
  await addFiles('Preview тренда', [image('public.jpg')])
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать тренд' }))
  await waitFor(() => expect(submitPrompt).toHaveBeenCalledTimes(1))
  expect(mockedPublish).not.toHaveBeenCalled()
})

it('shows upload failure, restores controls and lets the admin retry', async () => {
  await openSeedance()
  mockedUpload.mockRejectedValueOnce(new Error('Не удалось загрузить файл'))
  await addFiles('Фото-референсы тренда', [image('face.jpg')])
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить файл')
  expect(screen.queryByAltText('Исходный @Image1')).not.toBeInTheDocument()
  await addFiles('Фото-референсы тренда', [image('face.jpg')])
  expect(screen.getByAltText('Исходный @Image1')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})


it('rejects a batch above model reference caps before uploading any files', async () => {
  await openSeedance()
  await addFiles('Фото-референсы тренда', [image('one.jpg'), image('two.jpg'), image('three.jpg')])
  expect(screen.getByRole('alert')).toHaveTextContent('Фото: максимум 2')
  expect(mockedUpload).not.toHaveBeenCalled()
  await addFiles('Фото-референсы тренда', [image('one.jpg'), image('two.jpg')])
  await addFiles('Фото-референсы тренда', [image('three.jpg')])
  expect(mockedUpload).toHaveBeenCalledTimes(2)
  expect(screen.getByRole('alert')).toHaveTextContent('Фото: максимум 2')
})

it('uses a Telegram-compatible first video frame while preserving the original upload URL', async () => {
  await openSeedance()
  await addFiles('Видео-референсы тренда', [new File(['video'], 'motion.mp4', { type: 'video/mp4' })])
  expect(screen.getByLabelText('Исходный @Video1')).toHaveAttribute('src', 'https://media.example/motion.mp4#t=0.001')
})


it('retains ordinary draft fields and completed preview when closing the form', async () => {
  render(<TrendsTab />)
  fireEvent.click(screen.getByRole('button', { name: 'Добавить' }))
  fireEvent.change(screen.getByPlaceholderText('Название тренда'), { target: { value: 'Keep my draft' } })
  await addFiles('Preview тренда', [image('public.jpg')])
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
  fireEvent.click(screen.getByRole('button', { name: 'Добавить' }))
  expect(screen.getByPlaceholderText('Название тренда')).toHaveValue('Keep my draft')
  expect(screen.getByAltText('Preview тренда')).toHaveAttribute('src', 'https://media.example/public.jpg')
})

it('requires an explicit positive Seedance 2.5 duration when own references are added', async () => {
  await openSeedance('seedance_2_5')
  fireEvent.change(screen.getByLabelText('Длительность'), { target: { value: '-1' } })
  expect(screen.getByLabelText('Длительность')).toHaveValue('-1')
  await addFiles('Фото-референсы тренда', [image('face.jpg')])
  expect(screen.getByLabelText('Длительность')).toHaveValue('5')
  expect(screen.queryByRole('option', { name: '-1 сек' })).not.toBeInTheDocument()
})


it('uses the existing chunk-capable Seedance 2.5 video uploader for an 80 MB reference', async () => {
  await openSeedance('seedance_2_5')
  const file = new File(['synthetic'], 'large-motion.mp4', { type: 'video/mp4' })
  Object.defineProperty(file, 'size', { value: 80 * 1024 * 1024 })
  await addFiles('Видео-референсы тренда', [file])
  expect(uploadSeedance25Video).toHaveBeenCalledWith(file)
  expect(mockedUpload).not.toHaveBeenCalled()
  expect(screen.getByLabelText('Исходный @Video1')).toHaveAttribute('src', 'https://media.example/large-motion.mp4#t=0.001')
})
