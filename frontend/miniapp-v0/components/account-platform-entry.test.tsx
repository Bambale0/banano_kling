import { render, screen, act } from '@testing-library/react'
import { AccountPlatformEntry } from './account-platform-entry'

jest.mock('@/lib/account-platform', () => ({
  hasVkLaunchData: () => false,
  incomingAccountLink: () => null,
}))
jest.mock('@/lib/vk-launch-telemetry', () => ({ reportVkLaunchStage: () => undefined }))
jest.mock('@/components/vk-native-workspace', () => ({ VkNativeWorkspace: () => null }))
jest.mock('@/components/shared-account-link-preview', () => ({ SharedAccountLinkPreview: () => null }))
jest.mock('@/lib/shared-account-api', () => ({
  startAccountAppSession: jest.fn(), stopAccountAppSession: jest.fn(),
}))
jest.mock('@/components/web-account-workspace', () => ({
  WebAccountWorkspace: () => <h1>Независимый веб-аккаунт</h1>,
}))

jest.mock('@/lib/web-account-entry', () => ({
  ...jest.requireActual('@/lib/web-account-entry'),
  navigateToWebsiteLogin: jest.fn(),
}))
import { navigateToWebsiteLogin } from '@/lib/web-account-entry'
const mockedNavigate = navigateToWebsiteLogin as jest.Mock

const originalFetch = global.fetch
beforeEach(() => {
  mockedNavigate.mockClear()
  window.history.replaceState({}, '', '/mini-app/')
  window.Telegram = undefined
  delete window.__BANANO_INITIAL_LAUNCH__
})
afterEach(() => {
  global.fetch = originalFetch
  window.history.replaceState({}, '', '/mini-app/')
  window.Telegram = undefined
  delete window.__BANANO_INITIAL_LAUNCH__
})

test('Yandex-only cookie opens web workspace, not Telegram Mini App store', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true, json: async () => ({
      ok: true, authenticated: true, studio_ready: false,
    }),
  }) as typeof fetch
  render(<AccountPlatformEntry><p>Telegram Mini App store</p></AccountPlatformEntry>)
  await screen.findByRole('heading', { name: 'Независимый веб-аккаунт' })
  expect(screen.queryByText('Telegram Mini App store')).toBeNull()
  expect(global.fetch).toHaveBeenCalledWith('/mini-app/api/web-auth/config',
    expect.objectContaining({ credentials: 'same-origin', cache: 'no-store' }))
})

test('explicit native Telegram launch never calls the web session gate', async () => {
  window.history.replaceState({}, '', '/mini-app/#tgWebAppData=signed-native-session')
  const fakeFetch = jest.fn()
  global.fetch = fakeFetch as typeof fetch
  render(<AccountPlatformEntry><p>Telegram Mini App store</p></AccountPlatformEntry>)
  await screen.findByText('Telegram Mini App store')
  expect(fakeFetch).not.toHaveBeenCalled()
})


test('anonymous external-browser visitor is sent to website login, never the Telegram bootstrap', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true, json: async () => ({
      ok: true, authenticated: false, studio_ready: false,
    }),
  }) as typeof fetch
  window.history.replaceState({}, '', '/mini-app/?ref=NW0123456789ABCDEF&unknown=value')
  render(<AccountPlatformEntry><p>Telegram Mini App store</p></AccountPlatformEntry>)
  await screen.findByText('Для продолжения войдите в NEUROMIX')
  expect(mockedNavigate).toHaveBeenCalledWith('/login?ref=NW0123456789ABCDEF')
  expect(screen.queryByText('Telegram Mini App store')).toBeNull()
  expect(screen.getByRole('link', { name: 'Войти в аккаунт' }).getAttribute('href'))
    .toBe('/login?ref=NW0123456789ABCDEF')
})


test('slow browser auth shows an actionable error instead of a permanent blank screen', async () => {
  jest.useFakeTimers()
  try {
    global.fetch = jest.fn().mockImplementation(() => new Promise(() => undefined)) as typeof fetch
    render(<AccountPlatformEntry><p>Telegram Mini App store</p></AccountPlatformEntry>)
    expect(screen.getByRole('status').textContent).toMatch(/Проверяем авторизацию/)
    await act(async () => {
      jest.advanceTimersByTime(10001)
      await Promise.resolve()
    })
    expect(screen.getByRole('alert').textContent).toMatch(/Проверьте соединение/)
    expect(screen.getByRole('link', { name: 'Повторить' }).getAttribute('href')).toBe('/mini-app/')
    expect(screen.queryByText('Telegram Mini App store')).toBeNull()
  } finally {
    jest.useRealTimers()
  }
})
