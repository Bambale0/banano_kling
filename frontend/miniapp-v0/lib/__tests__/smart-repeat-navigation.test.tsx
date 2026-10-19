import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AppProvider, useApp } from '../app-context'
import { bootstrapApp, fetchFeedItem, getStartParamFallback } from '../api'
import { hydrateSeedance25IdentityPreset } from '../seedance25-repeat'

jest.mock('../api', () => ({
  bootstrapApp: jest.fn(), fetchFeedItem: jest.fn(), fetchPromptDetail: jest.fn(), fetchTaskDetail: jest.fn(),
  getInitData: jest.fn(() => 'fixture'), getStartParamFallback: jest.fn(),
  hasTelegramInitData: jest.fn(() => true), waitForTelegramInitData: jest.fn(async () => true),
}))
jest.mock('../genjutsu-api', () => ({ genjutsuCall: jest.fn(), openGenjutsu: jest.fn() }))
jest.mock('../seedance25-repeat', () => ({ hydrateSeedance25IdentityPreset: jest.fn(async (_item, preset) => preset) }))
const base = { telegram_id: 1, credits: 100, smart_repeat_enabled: true, image_models: [], video_models: [], recent_tasks: [], saved_references: [] }
function Harness() {
  const app = useApp()
  return <>
    <output data-testid="mode">{app.state.mode}</output>
    <output data-testid="tab">{app.activeTab}</output>
    <output data-testid="profile">{app.viewedProfileCode}</output>
    <output data-testid="source">{app.smartRepeatSourceId}</output>
    <output data-testid="image">{app.promptPreset?.model}</output>
    <output data-testid="video">{app.videoPromptPreset?.model}</output>
    <output data-testid="error">{app.state.error}</output>
    <button onClick={app.closeSmartRepeat}>Close repeat</button>
    <button onClick={() => void app.refreshTasks()}>Refresh</button>
    <button onClick={() => { app.setPromptPreset({ title: 'Old image', prompt: '', model: 'old-image' }); app.setVideoPromptPreset({ title: 'Old video', prompt: '', model: 'old-video' }) }}>Old forms</button>
    <button onClick={() => app.setPromptPreset({ title: 'Repeat', prompt: '', model: 'source-model', sourceFeedGenId: 42 })}>Repeat image</button>
  </>
}
beforeEach(() => {
  jest.clearAllMocks()
  window.history.replaceState({}, '', '/mini-app/')
  ;(bootstrapApp as jest.Mock).mockResolvedValue(base)
  ;(getStartParamFallback as jest.Mock).mockReturnValue('remix_42')
})
test.each(['image', 'video'])('smart %s deep link uses server source without opening or hydrating a different generator', async kind => {
  ;(fetchFeedItem as jest.Mock).mockResolvedValue({ id: 42, gen_type: kind, model: 'source-model-not-in-catalog', publication_scope: 'feed' })
  render(<AppProvider><Harness /></AppProvider>)
  await waitFor(() => expect(screen.getByTestId('source')).toHaveTextContent('42'))
  expect(screen.getByTestId('tab')).toHaveTextContent('4')
  expect(screen.getByTestId('image')).toBeEmptyDOMElement()
  expect(screen.getByTestId('video')).toBeEmptyDOMElement()
  expect(hydrateSeedance25IdentityPreset).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('Close repeat'))
  fireEvent.click(screen.getByText('Refresh'))
  await waitFor(() => expect(bootstrapApp).toHaveBeenCalledTimes(2))
  expect(screen.getByTestId('source')).toBeEmptyDOMElement()
  expect(fetchFeedItem).toHaveBeenCalledTimes(1)
})
test('profile repeat deep link keeps the author profile behind the dialog', async () => {
  ;(fetchFeedItem as jest.Mock).mockResolvedValue({ id: 42, gen_type: 'image', model: 'source-model', publication_scope: 'profile', author_referral_code: 'AUTHOR' })
  render(<AppProvider><Harness /></AppProvider>)
  await waitFor(() => expect(screen.getByTestId('source')).toHaveTextContent('42'))
  expect(screen.getByTestId('tab')).toHaveTextContent('7')
  expect(screen.getByTestId('profile')).toHaveTextContent('AUTHOR')
})
test.each(['image', 'video'])('legacy %s link rejects unavailable source model instead of substituting a default', async kind => {
  ;(bootstrapApp as jest.Mock).mockResolvedValue({ ...base, smart_repeat_enabled: false,
    image_models: [{ id: 'banana_pro' }], video_models: [{ id: 'seedance_2_5' }] })
  ;(fetchFeedItem as jest.Mock).mockResolvedValue({ id: 42, gen_type: kind, model: 'unavailable-model', publication_scope: 'feed' })
  render(<AppProvider><Harness /></AppProvider>)
  await waitFor(() => expect(screen.getByTestId('error')).toHaveTextContent('Модель исходной работы недоступна'))
  expect(screen.getByTestId('image')).toBeEmptyDOMElement()
  expect(screen.getByTestId('video')).toBeEmptyDOMElement()
  expect(hydrateSeedance25IdentityPreset).not.toHaveBeenCalled()
})
test('opening a smart repeat clears both older generator presets', async () => {
  ;(getStartParamFallback as jest.Mock).mockReturnValue('')
  render(<AppProvider><Harness /></AppProvider>)
  await waitFor(() => expect(screen.getByTestId('mode')).toHaveTextContent('live'))
  fireEvent.click(screen.getByText('Old forms'))
  expect(screen.getByTestId('image')).toHaveTextContent('old-image')
  fireEvent.click(screen.getByText('Repeat image'))
  expect(screen.getByTestId('source')).toHaveTextContent('42')
  expect(screen.getByTestId('image')).toBeEmptyDOMElement()
  expect(screen.getByTestId('video')).toBeEmptyDOMElement()
})

test('an explicitly selected repeat fences a delayed older deep link', async () => {
  ;(getStartParamFallback as jest.Mock).mockReturnValue('remix_99')
  let resolve!: (item: unknown) => void
  ;(fetchFeedItem as jest.Mock).mockImplementationOnce(() => new Promise(done => { resolve = done }))
  render(<AppProvider><Harness /></AppProvider>)
  await waitFor(() => expect(fetchFeedItem).toHaveBeenCalledWith(99))
  fireEvent.click(screen.getByText('Repeat image'))
  await act(async () => resolve({ id: 99, gen_type: 'video', model: 'older-source', publication_scope: 'feed' }))
  expect(screen.getByTestId('source')).toHaveTextContent('42')
  expect(hydrateSeedance25IdentityPreset).not.toHaveBeenCalled()
})
