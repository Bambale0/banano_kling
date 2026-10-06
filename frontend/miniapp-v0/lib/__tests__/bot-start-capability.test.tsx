import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { AppProvider, useApp } from '../app-context'
import { bootstrapApp } from '../api'

jest.mock('../api', () => ({
  bootstrapApp: jest.fn(), fetchFeedItem: jest.fn(), fetchPromptDetail: jest.fn(), fetchTaskDetail: jest.fn(),
  getInitData: jest.fn(() => 'fixture'), getStartParamFallback: jest.fn(() => ''),
  hasTelegramInitData: jest.fn(() => true), waitForTelegramInitData: jest.fn(async () => true),
}))
jest.mock('../genjutsu-api', () => ({ genjutsuCall: jest.fn(), openGenjutsu: jest.fn() }))
const payload = { telegram_id: 1, credits: 100, telegram_chat_available: false, image_models: [], video_models: [], recent_tasks: [],
  saved_references: [{ id: 9, filename: 'reference.png', kind: 'image', url: '/fixture.png' }] }
const bootstrap = bootstrapApp as jest.Mock
let controller: AbortController
function Harness() {
  const app = useApp()
  const [error, setError] = useState('')
  return <>
    <output data-testid="access">{String(app.state.user.telegramChatAvailable)}</output>
    <output data-testid="loading">{String(app.state.isLoading)}</output>
    <output data-testid="references">{app.state.savedReferences.map(ref => ref.name).join(',')}</output>
    <output data-testid="tab">{app.activeTab}</output>
    <output data-testid="error">{error}</output>
    {!app.state.isLoading && <input aria-label="Draft" defaultValue="draft prompt" />}
    <button onClick={() => app.setActiveTab(1)}>Photo</button>
    <button onClick={() => { controller = new AbortController(); void app.refreshTelegramChatAccess(controller.signal).catch(() => setError('failed')) }}>Check</button>
  </>
}
beforeEach(() => {
  jest.clearAllMocks()
  window.history.replaceState({}, '', '/mini-app/')
  bootstrap.mockResolvedValue(payload)
})
async function mount() {
  render(<AppProvider><Harness /></AppProvider>)
  await screen.findByRole('textbox')
}

test('capability refresh keeps the draft DOM, active tab and references mounted', async () => {
  await mount()
  fireEvent.click(screen.getByText('Photo'))
  const input = screen.getByRole('textbox')
  fireEvent.change(input, { target: { value: 'edited draft' } })
  let resolve!: (data: unknown) => void
  bootstrap.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  fireEvent.click(screen.getByText('Check'))
  expect(screen.getByTestId('loading')).toHaveTextContent('false')
  expect(screen.getByRole('textbox')).toBe(input)
  await act(async () => resolve({ ...payload, telegram_chat_available: true, saved_references: [] }))
  expect(screen.getByTestId('access')).toHaveTextContent('true')
  expect(screen.getByTestId('references')).toHaveTextContent('reference.png')
  expect(screen.getByTestId('tab')).toHaveTextContent('1')
  expect(screen.getByRole('textbox')).toBe(input)
  expect(input).toHaveValue('edited draft')
})

test('aborted late confirmation cannot unlock the app', async () => {
  await mount()
  let resolve!: (data: unknown) => void
  bootstrap.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  fireEvent.click(screen.getByText('Check'))
  controller.abort()
  await act(async () => resolve({ ...payload, telegram_chat_available: true }))
  expect(screen.getByTestId('access')).toHaveTextContent('false')
  expect(screen.getByTestId('error')).toHaveTextContent('failed')
})

test('an older background snapshot cannot reopen access after Start confirmation', async () => {
  await mount()
  let resolveOld!: (data: unknown) => void
  bootstrap.mockImplementationOnce(() => new Promise(done => { resolveOld = done }))
  fireEvent.focus(window)
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(2))
  bootstrap.mockResolvedValueOnce({ ...payload, telegram_chat_available: true })
  fireEvent.click(screen.getByText('Check'))
  await waitFor(() => expect(screen.getByTestId('access')).toHaveTextContent('true'))
  await act(async () => resolveOld(payload))
  expect(screen.getByTestId('access')).toHaveTextContent('true')
  // A genuinely newer revocation must still be respected.
  bootstrap.mockResolvedValueOnce(payload)
  fireEvent.focus(window)
  await waitFor(() => expect(screen.getByTestId('access')).toHaveTextContent('false'))
})

test('missing server capability cannot unlock an already required gate', async () => {
  await mount()
  const { telegram_chat_available: _available, ...missing } = payload
  bootstrap.mockResolvedValue(missing)
  fireEvent.focus(window)
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(2))
  expect(screen.getByTestId('access')).toHaveTextContent('false')
  fireEvent.click(screen.getByText('Check'))
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(3))
  expect(screen.getByTestId('access')).toHaveTextContent('false')
})
