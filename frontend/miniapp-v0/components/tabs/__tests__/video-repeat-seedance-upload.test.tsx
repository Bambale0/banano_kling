import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { VideoTab } from '../video-tab'
import { useApp } from '@/lib/app-context'
import { generateVideo, uploadFile } from '@/lib/api'

jest.mock('@/components/genjutsu-entry', () => ({ GenjutsuButton: () => null }))
jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({ generateVideo: jest.fn(), uploadFile: jest.fn(), sendMiniAppClientLog: jest.fn(), getApiBasePath: () => '/mini-app/api', getInitData: () => 'signed', getStartParamFallback: () => '' }))
jest.mock('@/components/forms/scenario-select', () => ({ ScenarioSelect: ({ value }: { value: string }) => <span>{value}</span> }))
const upload = uploadFile as jest.MockedFunction<typeof uploadFile>
function setup(model: string) {
  ;(useApp as jest.Mock).mockReturnValue({
    state: { mode: 'live', user: { credits: 100, isAdmin: false }, videoModels: [{ id: model, label: model, description: 'Synthetic', supports: ['video'], durations: [5], ratios: ['16:9'], costs: { '5': 5 }, max_video_references: 5 }], savedReferences: [] },
    videoPromptPreset: { title: 'Repeat', prompt: '', model, scenario: 'video', ratio: '16:9', duration: 5, sourceFeedGenId: 481,
      repeatReferenceSlots: { version: 1, available: true, cost_multiplier: 2, duration_costs: { '5': 10 }, pricing_quality: '720p', images: [], videos: [{ index: 0, role: 'reference', binding: 'upload' }] } },
    setVideoPromptPreset: jest.fn(), addSavedReference: jest.fn(), refreshTasks: jest.fn(), setActiveTab: jest.fn(),
  })
}
beforeEach(() => {
  jest.clearAllMocks()
  window.sessionStorage.clear()
  upload.mockImplementation(async (kind, file) => {
    if (kind === 'video_reference' && file.size > 50 * 1024 * 1024) throw new Error('Generic upload limit: 50 MB')
    return { id: file.name, name: file.name, url: `https://example.test/${file.name}`, type: 'video', size: file.size }
  })
  global.fetch = jest.fn().mockResolvedValue({ ok: true, text: async () => JSON.stringify({ ok: true, url: 'https://example.test/assembled.mp4', kind: 'video', filename: 'big.mp4' }) })
})

it('routes a typed Seedance replacement above 50 MB through the real chunk assembly uploader', async () => {
  setup('seedance_2_5')
  const view = render(<VideoTab />)
  const file = new File(['synthetic'], 'big.mp4', { type: 'video/mp4' })
  Object.defineProperty(file, 'size', { value: 60 * 1024 * 1024 })
  jest.spyOn(file, 'slice').mockImplementation(() => new Blob(['synthetic-chunk'], { type: 'video/mp4' }))
  fireEvent.change(view.container.querySelector('input[type=file]')!, { target: { files: [file] } })
  await waitFor(() => expect(upload).toHaveBeenCalledWith('seedance25_video_chunk', expect.any(File)))
  await screen.findByText('big.mp4')
  expect(upload).toHaveBeenCalledTimes(9)
  expect(upload.mock.calls.every(([kind]) => kind === ('seedance25_video_chunk' as never))).toBe(true)
  expect(fetch).toHaveBeenCalledTimes(1)
  const [url, options] = (fetch as jest.Mock).mock.calls[0]
  expect(url).toBe('/mini-app/api/generate-video')
  expect(JSON.parse(options.body)).toMatchObject({ seedance25_upload_only: true, v_model: 'seedance_2_5', seedance25_original_size: file.size })
  expect(generateVideo).not.toHaveBeenCalled()
})

it('keeps other models on the ordinary video uploader', async () => {
  setup('seedance_2')
  const view = render(<VideoTab />)
  const file = new File(['synthetic'], 'ordinary.mp4', { type: 'video/mp4' })
  fireEvent.change(view.container.querySelector('input[type=file]')!, { target: { files: [file] } })
  await waitFor(() => expect(upload).toHaveBeenCalledWith('video_reference', file))
  expect(fetch).not.toHaveBeenCalled()
  expect(generateVideo).not.toHaveBeenCalled()
})


it('uses the Seedance direct kind for a small typed replacement', async () => {
  setup('seedance_2_5')
  const view = render(<VideoTab />)
  const file = new File(['synthetic'], 'small.mp4', { type: 'video/mp4' })
  fireEvent.change(view.container.querySelector('input[type=file]')!, { target: { files: [file] } })
  await waitFor(() => expect(upload).toHaveBeenCalledWith('seedance25_video_reference', file))
  expect(fetch).not.toHaveBeenCalled()
  expect(generateVideo).not.toHaveBeenCalled()
})
