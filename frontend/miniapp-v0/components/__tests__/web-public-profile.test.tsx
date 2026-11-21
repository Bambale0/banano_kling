import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import { BrowserAccountWorkspace } from '../browser-account-workspace'

const oldFetch = global.fetch
afterEach(() => {
  global.fetch = oldFetch
  window.history.replaceState({}, '', '/mini-app/')
})

test('anonymous public profile opens without Telegram or a private web session', async () => {
  window.history.replaceState({}, '', '/mini-app/?web=1&profile=WABCDEF12345678&ref=WABCDEF12345678')
  const fetchMock = jest.fn().mockImplementation(async (url: string) => {
    if (!url.startsWith('/mini-app/api/web-auth/public-profile?code=')) {
      throw new Error('private actor must not be queried for an anonymous profile: ' + url)
    }
    return { ok: true, status: 200, json: async () => ({
      ok: true, code: 'WABCDEF12345678', display_name: 'Автор NEUROMIX',
    }) }
  })
  global.fetch = fetchMock as typeof fetch
  render(<BrowserAccountWorkspace />)
  expect(await screen.findByRole('heading', { name: 'Автор NEUROMIX' })).toBeInTheDocument()
  const entry = screen.getByRole('link', { name: 'Присоединиться по приглашению' })
  expect(entry).toHaveAttribute('href', 'http://localhost/login?web=1&ref=WABCDEF12345678')
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(screen.queryByText('Мои генерации')).not.toBeInTheDocument()
  expect(screen.queryByText(/t\.me/)).not.toBeInTheDocument()
})

test('verified independent browser gets server-owned share URLs and attributes invitation once', async () => {
  window.history.replaceState({}, '', '/mini-app/?web=1&ref=INVITER123')
  const reads: string[] = []
  const fetchMock = jest.fn().mockImplementation(async (url: string, options: Record<string, unknown>) => {
    reads.push(url)
    if (url.endsWith('/actor')) return {
      ok: true, status: 200,
      json: async () => ({
        ok: true, account_id: 'verified_owner', auth_channel: 'web',
        telegram_linked: false, wallet_authority: 'web_live',
      }),
    }
    if (url.endsWith('/catalog')) return {
      ok: true, status: 200, json: async () => ({
        ok: true, web_generate_enabled: false, image_models: [], video_models: [],
      }),
    }
    if (url.endsWith('/history')) return {
      ok: true, status: 200, json: async () => ({
        ok: true, recent_tasks: [], scope: 'web_only', next_cursor: null, cursor_reset: false,
      }),
    }
    if (url.endsWith('/public-links')) return {
      ok: true, status: 200, json: async () => ({
        ok: true, code: 'WOWNED123456789',
        profile_link: 'http://localhost/mini-app/?web=1&profile=WOWNED123456789&ref=WOWNED123456789',
        referral_link: 'http://localhost/login?web=1&ref=WOWNED123456789',
      }),
    }
    if (url.endsWith('/referral/attach')) {
      expect(options).toEqual(expect.objectContaining({
        method: 'POST', credentials: 'same-origin',
        body: JSON.stringify({ code: 'INVITER123' }),
      }))
      return { ok: true, status: 200, json: async () => ({ ok: true, attached: true }) }
    }
    throw new Error('unexpected call: ' + url)
  })
  global.fetch = fetchMock as typeof fetch
  render(<BrowserAccountWorkspace />)
  expect(await screen.findByRole('link', { name: 'http://localhost/login?web=1&ref=WOWNED123456789' }))
    .toBeInTheDocument()
  expect(await screen.findByText('Приглашение закреплено за веб-аккаунтом.')).toBeInTheDocument()
  expect(reads.filter(url => url.endsWith('/referral/attach'))).toHaveLength(1)
  expect(screen.queryByText(/https:\/\/t\.me/)).not.toBeInTheDocument()
})

test('public profile does not display private task or email even if API rejects', async () => {
  window.history.replaceState({}, '', '/mini-app/?web=1&profile=WNOTFOUND')
  global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 404 }) as typeof fetch
  render(<BrowserAccountWorkspace />)
  expect(await screen.findByText('Профиль не найден или временно недоступен.')).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByText('Мои генерации')).not.toBeInTheDocument())
})


test('expired browser login preserves referral code rather than dropping to /login', async () => {
  window.history.replaceState({}, '', '/mini-app/?web=1&ref=INVITER123')
  const fetchMock = jest.fn().mockResolvedValue({ ok: false, status: 401 })
  global.fetch = fetchMock as typeof fetch
  render(<BrowserAccountWorkspace />)
  expect(await screen.findByRole('link', { name: 'Войти в NEUROMIX' }))
    .toHaveAttribute('href', '/login?web=1&ref=INVITER123')
  expect(fetchMock).toHaveBeenCalledTimes(1)
})
