import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Seedance25PublicForm } from './seedance25-public-form'
import { generateSeedance25, quoteSeedance25Identity } from '@/lib/seedance25-api'
import type { VideoPromptPreset } from '@/lib/types'

jest.mock('@/lib/seedance25-api', () => ({
  SEEDANCE25_MAX_PROMPT_LENGTH: 30000, generateSeedance25: jest.fn(), quoteSeedance25Identity: jest.fn(), uploadSeedance25Video: jest.fn(),
}))
jest.mock('@/lib/api', () => ({ uploadFile: jest.fn() }))
const quote = { ok: true, quote_only: true, cost: 88, billing_duration: 11, source_video_duration_seconds: 10.04,
  seedance25_identity_quote: { cost: 88, billing_duration: 11, source_video_url: 'https://example.test/source.mp4', resolution: '720p', source_feed_gen_id: 42, parent_generation_id: 42 } }
const preset: VideoPromptPreset = {
  title: 'Repeat', prompt: '', model: 'seedance_2_5', sourceFeedGenId: 42, promptHidden: true,
  seedance25IdentityTransfer: true, seedance25Resolution: '720p',
  initialPhotoReferences: ['front', 'profile'].map(name => ({ id: name, name: name + '.png', url: 'https://example.test/' + name + '.png', type: 'image', size: 1 })),
  initialVideoReferences: [{ id: 'source', name: 'source.mp4', url: 'https://example.test/source.mp4', type: 'video', size: 1 }],
}
beforeEach(() => {
  jest.resetAllMocks()
  ;(quoteSeedance25Identity as jest.Mock).mockResolvedValue(quote)
  ;(generateSeedance25 as jest.Mock).mockResolvedValue({ ok: true, task_id: 'mock', cost: 88, admin_free: false })
})
it('restores identity repeat with ordered roles and fresh quote before an explicit launch', async () => {
  render(<Seedance25PublicForm credits={1000} isAdmin={false} promptPreset={preset} />)
  expect(screen.getByLabelText('Промпт для Seedance 2.5')).toHaveValue('')
  expect(screen.getByText('@Image1 · внешность')).toBeInTheDocument()
  expect(screen.getByText('@Image2 · внешность')).toBeInTheDocument()
  await waitFor(() => expect(quoteSeedance25Identity).toHaveBeenCalledWith(expect.objectContaining({
    sourceFeedGenId: 42, identityTransfer: true, prompt: '',
    referenceImages: ['https://example.test/front.png', 'https://example.test/profile.png'],
    referenceVideos: ['https://example.test/source.mp4'],
  })))
  expect(generateSeedance25).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText('Промпт для Seedance 2.5'), { target: { value: 'Additional instruction' } })
  await waitFor(() => expect(quoteSeedance25Identity).toHaveBeenLastCalledWith(expect.objectContaining({ sourceFeedGenId: 42, prompt: 'Additional instruction' })))
  await waitFor(() => expect(screen.getByRole('button', { name: '🚀 Создать видео · 88🍌' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '🚀 Создать видео · 88🍌' }))
  await waitFor(() => expect(generateSeedance25).toHaveBeenCalledWith(expect.objectContaining({
    sourceFeedGenId: 42, identityTransfer: true, prompt: 'Additional instruction', identityQuote: quote.seedance25_identity_quote,
  })))
})
it('clears repeat lineage when returning to ordinary references without losing photos', async () => {
  render(<Seedance25PublicForm credits={1000} isAdmin={false} promptPreset={preset} />)
  await screen.findByRole('button', { name: '🚀 Создать видео · 88🍌' })
  fireEvent.click(screen.getByRole('button', { name: /По референсам Использовать/ }))
  expect(screen.getByText('front.png')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Длительность видео'), { target: { value: '15' } })
  fireEvent.click(screen.getByRole('button', { name: /Создать видео/ }))
  await waitFor(() => expect(generateSeedance25).toHaveBeenCalledWith(expect.objectContaining({
    sourceFeedGenId: null, identityTransfer: false, duration: 15, identityQuote: undefined,
  })))
})
it('removing the source prevents both quote and generation rather than silently restoring it', async () => {
  render(<Seedance25PublicForm credits={1000} isAdmin={false} promptPreset={preset} />)
  await screen.findByRole('button', { name: '🚀 Создать видео · 88🍌' })
  ;(quoteSeedance25Identity as jest.Mock).mockClear()
  fireEvent.click(screen.getAllByRole('button', { name: 'Удалить файл' })[2])
  expect(screen.getByText('Добавьте ровно одно исходное видео')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Добавьте фото и исходное видео' })).toBeDisabled()
  expect(quoteSeedance25Identity).not.toHaveBeenCalled()
  expect(generateSeedance25).not.toHaveBeenCalled()
})

it('invalidates a rejected quote and requires another explicit launch at the refreshed price', async () => {
  ;(quoteSeedance25Identity as jest.Mock).mockReset().mockResolvedValueOnce(quote).mockResolvedValue({ ...quote, cost: 96, seedance25_identity_quote: { ...quote.seedance25_identity_quote, cost: 96 } })
  ;(generateSeedance25 as jest.Mock).mockRejectedValueOnce(new Error('Price changed'))
  render(<Seedance25PublicForm credits={1000} isAdmin={false} promptPreset={preset} />)
  fireEvent.click(await screen.findByRole('button', { name: '🚀 Создать видео · 88🍌' }))
  await screen.findByText('Price changed')
  await screen.findByRole('button', { name: '🚀 Создать видео · 96🍌' })
  expect(quoteSeedance25Identity).toHaveBeenCalledTimes(2)
  expect(generateSeedance25).toHaveBeenCalledTimes(1)
})


it('never restores hidden text from a stale identity preset, including reopening', async () => {
  const hidden = { ...preset, prompt: 'SYNTHETIC_PRIVATE_IDENTITY_RECIPE' }
  const view = render(<Seedance25PublicForm credits={1000} isAdmin={false} promptPreset={hidden} />)
  expect(screen.getByLabelText('Промпт для Seedance 2.5')).toHaveValue('')
  await waitFor(() => expect(quoteSeedance25Identity).toHaveBeenCalledWith(expect.objectContaining({ prompt: '' })))
  fireEvent.change(screen.getByLabelText('Промпт для Seedance 2.5'), { target: { value: 'My change' } })
  view.rerender(<Seedance25PublicForm credits={1000} isAdmin={false} promptPreset={{ ...hidden, sourceFeedGenId: 43 }} />)
  expect(screen.getByLabelText('Промпт для Seedance 2.5')).toHaveValue('')
  view.unmount()
  render(<Seedance25PublicForm credits={1000} isAdmin={false} promptPreset={hidden} />)
  expect(screen.getByLabelText('Промпт для Seedance 2.5')).toHaveValue('')
  expect(generateSeedance25).not.toHaveBeenCalled()
})

it('keeps the visible ordinary owner identity instruction', () => {
  render(<Seedance25PublicForm credits={1000} isAdmin={false} promptPreset={{ ...preset, promptHidden: false, prompt: 'Owner instruction' }} />)
  expect(screen.getByLabelText('Промпт для Seedance 2.5')).toHaveValue('Owner instruction')
})
