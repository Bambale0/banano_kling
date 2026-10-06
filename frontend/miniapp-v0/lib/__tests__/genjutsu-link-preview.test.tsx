import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AppProvider, useApp } from '../app-context'
import { bootstrapApp, fetchFeedItem, getStartParamFallback } from '../api'
import { genjutsuCall, openGenjutsu } from '../genjutsu-api'

jest.mock('../api', () => ({
  bootstrapApp: jest.fn(), fetchFeedItem: jest.fn(), fetchPromptDetail: jest.fn(), fetchTaskDetail: jest.fn(),
  getInitData: jest.fn(() => 'fixture'), getStartParamFallback: jest.fn(),
  hasTelegramInitData: jest.fn(() => true), waitForTelegramInitData: jest.fn(async () => true),
}))
jest.mock('../genjutsu-api', () => ({ genjutsuCall: jest.fn(), openGenjutsu: jest.fn() }))
const recipeId = 'a'.repeat(32)
const card = { id: 777, model: 'genjutsu', gen_type: 'video', genjutsu_recipe_id: recipeId,
  publication_scope: 'feed', author_referral_code: 'AUTHOR', result_url: 'https://example.test/output.mp4' }
const bootstrap = { telegram_id: 1, credits: 100, image_models: [], video_models: [], recent_tasks: [], saved_references: [] }
const call = genjutsuCall as jest.Mock
const start = getStartParamFallback as jest.Mock
function Harness() {
  const app = useApp()
  return <>
    <output data-testid="tab">{app.activeTab}</output>
    <output data-testid="profile">{app.viewedProfileCode}</output>
    <output data-testid="error">{app.state.error}</output>
    <output data-testid="generic">{app.videoPromptPreset?.model}</output>
    {app.feedDeepLink && <section aria-label="Video preview">
      <output data-testid="preview-id">{app.feedDeepLink.item.id}</output>
      <video src={app.feedDeepLink.item.result_url || ''} />
      <button onClick={() => { app.consumeFeedDeepLink(); openGenjutsu({ recipe_id: app.feedDeepLink!.item.genjutsu_recipe_id! }) }}>Repeat</button>
      <button onClick={app.consumeFeedDeepLink}>Close preview</button>
    </section>}
    <button onClick={() => app.setActiveTab(1)}>Leave</button>
    <button onClick={() => void app.refreshTasks()}>Refresh</button>
  </>
}
function mount() { return render(<AppProvider><Harness /></AppProvider>) }
beforeEach(() => {
  jest.clearAllMocks()
  window.history.replaceState({}, '', '/mini-app/')
  ;(bootstrapApp as jest.Mock).mockResolvedValue(bootstrap)
  ;(fetchFeedItem as jest.Mock).mockResolvedValue(card)
  call.mockResolvedValue({ card })
  start.mockReturnValue('genjutsu_recipe_' + recipeId)
})

test('legacy recipe link shows public video before explicit repeat', async () => {
  mount()
  expect(await screen.findByRole('region', { name: 'Video preview' })).toBeInTheDocument()
  expect(call).toHaveBeenCalledWith('recipe_preview', { recipe_id: recipeId })
  expect(openGenjutsu).not.toHaveBeenCalled()
  expect(screen.getByTestId('tab')).toHaveTextContent('4')
  fireEvent.click(screen.getByText('Repeat'))
  expect(openGenjutsu).toHaveBeenCalledWith({ recipe_id: recipeId })
  expect(screen.queryByRole('region')).not.toBeInTheDocument()
})


test.each(['feed', 'profile'])('query-only legacy link respects %s publication scope', async (scope) => {
  start.mockReturnValue('')
  window.history.replaceState({}, '', '/mini-app/?genjutsu=1&genjutsu_recipe=' + recipeId)
  call.mockResolvedValue({ card: { ...card, publication_scope: scope } })
  mount()
  await screen.findByRole('region', { name: 'Video preview' })
  expect(screen.getByTestId('tab')).toHaveTextContent(scope === 'profile' ? '7' : '4')
  if (scope === 'profile') expect(screen.getByTestId('profile')).toHaveTextContent('AUTHOR')
  expect(openGenjutsu).not.toHaveBeenCalled()
})

test.each(['feed_777_ref_AUTHOR', 'remix_777_ref_AUTHOR', 'remix_297231_ref_QM7QQ6XD', 'feed_297127_ref_XOCATI0Q'])('%s previews Genjutsu without a generic model fallback', async (value) => {
  start.mockReturnValue(value)
  const publicationId = Number(value.split('_')[1])
  ;(fetchFeedItem as jest.Mock).mockResolvedValue({ ...card, id: publicationId })
  mount()
  await screen.findByRole('region', { name: 'Video preview' })
  expect(fetchFeedItem).toHaveBeenCalledWith(publicationId)
  expect(screen.getByTestId('generic')).toBeEmptyDOMElement()
  expect(openGenjutsu).not.toHaveBeenCalled()
})

test('active curated recipe without a publication retains its studio entry', async () => {
  call.mockResolvedValue({ card: null })
  mount()
  await waitFor(() => expect(openGenjutsu).toHaveBeenCalledWith({ recipe_id: recipeId }))
  expect(screen.queryByRole('region')).not.toBeInTheDocument()
})

test('withdrawn recipe fails closed without editor or generic fallback', async () => {
  call.mockRejectedValue(new Error('Публикация недоступна'))
  mount()
  expect(await screen.findByText('Публикация недоступна')).toBeInTheDocument()
  expect(openGenjutsu).not.toHaveBeenCalled()
  expect(screen.queryByRole('region')).not.toBeInTheDocument()
})

test('closing preview does not reopen it on bootstrap refresh', async () => {
  mount()
  await screen.findByRole('region', { name: 'Video preview' })
  fireEvent.click(screen.getByText('Close preview'))
  fireEvent.click(screen.getByText('Refresh'))
  await waitFor(() => expect(bootstrapApp).toHaveBeenCalledTimes(2))
  expect(call).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('region')).not.toBeInTheDocument()
})

test('navigation away fences a late recipe response', async () => {
  let resolve!: (value: unknown) => void
  call.mockImplementation(() => new Promise(done => { resolve = done }))
  mount()
  await waitFor(() => expect(call).toHaveBeenCalled())
  fireEvent.click(screen.getByText('Leave'))
  await act(async () => resolve({ card }))
  expect(screen.queryByRole('region')).not.toBeInTheDocument()
  expect(screen.getByTestId('tab')).toHaveTextContent('1')
  fireEvent.click(screen.getByText('Refresh'))
  await waitFor(() => expect(bootstrapApp).toHaveBeenCalledTimes(2))
  expect(call).toHaveBeenCalledTimes(1)
})

test('newer history navigation wins over a slow old recipe link', async () => {
  let resolve!: (value: unknown) => void
  call.mockImplementation(() => new Promise(done => { resolve = done }))
  mount()
  await waitFor(() => expect(call).toHaveBeenCalled())
  ;(fetchFeedItem as jest.Mock).mockResolvedValue({ ...card, id: 888 })
  act(() => {
    window.history.pushState({}, '', '/mini-app/?startapp=feed_888_ref_AUTHOR')
    window.dispatchEvent(new PopStateEvent('popstate'))
  })
  await waitFor(() => expect(fetchFeedItem).toHaveBeenCalledWith(888))
  await screen.findByRole('region', { name: 'Video preview' })
  await act(async () => resolve({ card }))
  expect(call).toHaveBeenCalledTimes(1)
  expect(screen.getByTestId('preview-id')).toHaveTextContent('888')
  expect(openGenjutsu).not.toHaveBeenCalled()
})


test('missing resolver card does not fall through to the private editor', async () => {
  call.mockResolvedValue({})
  mount()
  await screen.findByText('Публикация недоступна. Обновите ссылку.')
  expect(openGenjutsu).not.toHaveBeenCalled()
})

test('Back to a clean location cancels the pending link and Forward can reopen it', async () => {
  let resolve!: (value: unknown) => void
  call.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  mount()
  await waitFor(() => expect(call).toHaveBeenCalledTimes(1))
  act(() => {
    window.history.replaceState({}, '', '/mini-app/')
    window.dispatchEvent(new PopStateEvent('popstate'))
  })
  await act(async () => resolve({ card }))
  expect(screen.queryByRole('region')).not.toBeInTheDocument()
  act(() => {
    window.history.replaceState({}, '', '/mini-app/?startapp=genjutsu_recipe_' + recipeId)
    window.dispatchEvent(new PopStateEvent('popstate'))
  })
  await screen.findByRole('region', { name: 'Video preview' })
  expect(call).toHaveBeenCalledTimes(2)
  expect(openGenjutsu).not.toHaveBeenCalled()
})

test('Telegram clearing its launch hash does not cancel delayed preview resolution', async () => {
  let resolve!: (value: unknown) => void
  call.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  mount()
  await waitFor(() => expect(call).toHaveBeenCalled())
  act(() => window.dispatchEvent(new HashChangeEvent('hashchange')))
  await act(async () => resolve({ card }))
  await screen.findByRole('region', { name: 'Video preview' })
})

test('a new hash link takes precedence over Telegram initial launch snapshot', async () => {
  mount()
  await screen.findByRole('region', { name: 'Video preview' })
  ;(fetchFeedItem as jest.Mock).mockResolvedValue({ ...card, id: 999 })
  act(() => {
    window.history.replaceState({}, '', '/mini-app/?foo=bar#tgWebAppStartParam=feed_999_ref_AUTHOR')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
  await waitFor(() => expect(screen.getByTestId('preview-id')).toHaveTextContent('999'))
})


test('a valid new link clears a previous unavailable-link error', async () => {
  call.mockRejectedValueOnce(new Error('Публикация недоступна'))
  mount()
  await screen.findByText('Публикация недоступна')
  act(() => {
    window.history.replaceState({}, '', '/mini-app/?startapp=feed_297127_ref_XOCATI0Q')
    window.dispatchEvent(new PopStateEvent('popstate'))
  })
  await screen.findByRole('region', { name: 'Video preview' })
  expect(screen.getByTestId('error')).toBeEmptyDOMElement()
})
