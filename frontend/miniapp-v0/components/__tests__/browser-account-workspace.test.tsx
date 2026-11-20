import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BrowserAccountWorkspace } from '../browser-account-workspace'

const responses = {
  actor: {
    ok: true, account_id: 'verified_account', auth_channel: 'web',
    telegram_linked: true, wallet_authority: 'web_live',
  },
  catalog: {
    ok: true, catalog_scope: 'read_only', web_generate_enabled: false,
    image_models: [{ id: 'nano_banana_pro', label: 'Nano Banana Pro', kind: 'image', web_generate_enabled: false }],
    video_models: [{ id: 'seedance_2_5', label: 'Seedance 2.5', kind: 'video', web_generate_enabled: false }],
  },
  history: {
    ok: true, scope: 'legacy_telegram', cursor_reset: false, next_cursor: null,
    recent_tasks: [{ task_id: 'owned-1', type: 'image', status: 'completed', created_at: '2026-11-20T00:00:00', prompt_preview: 'my picture', result_url: '/uploads/owned.png' }],
  },
  task: {
    ok: true, scope: 'legacy_telegram',
    task: { task_id: 'owned-1', type: 'image', status: 'completed', prompt_hidden: true, prompt: 'never render this secret', result_url: '/uploads/owned.png' },
  },
}
const mockFetch = jest.fn()

beforeEach(() => {
  mockFetch.mockReset()
  mockFetch.mockImplementation(async (input: string) => {
    const url = String(input)
    const data = url.includes('/actor') ? responses.actor :
      url.includes('/catalog') ? responses.catalog :
      url.includes('/history') ? responses.history : responses.task
    return { ok: true, status: 200, json: async () => data }
  })
  global.fetch = mockFetch
})

test('verified browser account sees real shared catalogue and owned history, and opens sanitized detail', async () => {
  render(<BrowserAccountWorkspace />)
  expect(await screen.findByText('Nano Banana Pro')).toBeInTheDocument()
  expect(screen.getByText('Seedance 2.5')).toBeInTheDocument()
  expect(await screen.findByText('my picture')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /создать|генерировать/i })).not.toBeInTheDocument()
  expect(mockFetch.mock.calls.every(([url, opts]) =>
    String(url).startsWith('/mini-app/api/web-auth/') &&
    opts.credentials === 'same-origin' && opts.cache === 'no-store')).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: /открыть задачу/i }))
  expect(await screen.findByText('owned-1')).toBeInTheDocument()
  expect(screen.queryByText('never render this secret')).not.toBeInTheDocument()
})

test('revoked web session cannot see catalogue or history and gets sign-in option', async () => {
  mockFetch.mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({ ok: false }) })
  render(<BrowserAccountWorkspace />)
  expect(await screen.findByRole('link', { name: /войти/i })).toHaveAttribute('href', '/login')
  expect(screen.queryByText('Nano Banana Pro')).not.toBeInTheDocument()
  expect(mockFetch).toHaveBeenCalledTimes(1)
})

test('logout clears read-only media and sends server revocation before offering login', async () => {
  mockFetch.mockImplementation(async (input: string) => {
    const url = String(input)
    if (url.endsWith('/logout')) return { ok: true, status: 200, json: async () => ({ ok: true }) }
    const data = url.includes('/actor') ? responses.actor :
      url.includes('/catalog') ? responses.catalog : responses.history
    return { ok: true, status: 200, json: async () => data }
  })
  render(<BrowserAccountWorkspace />)
  expect(await screen.findByText('my picture')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Выйти из веб-аккаунта' }))
  await waitFor(() => expect(mockFetch.mock.calls.some(([url, opts]) =>
    String(url).endsWith('/logout') && opts.method === 'POST')).toBe(true))
  expect(await screen.findByRole('link', { name: /войти/i })).toBeInTheDocument()
  expect(screen.queryByText('my picture')).not.toBeInTheDocument()
})

test('account revocation in another tab clears private history on returning focus', async () => {
  let actorReads = 0
  mockFetch.mockImplementation(async (input: string) => {
    const url = String(input)
    if (url.includes('/actor')) {
      actorReads += 1
      if (actorReads > 1) return { ok: false, status: 401, json: async () => ({ ok: false }) }
      return { ok: true, status: 200, json: async () => responses.actor }
    }
    return {
      ok: true, status: 200, json: async () =>
        url.includes('/catalog') ? responses.catalog : responses.history,
    }
  })
  render(<BrowserAccountWorkspace />)
  expect(await screen.findByText('my picture')).toBeInTheDocument()
  fireEvent.focus(window)
  expect(await screen.findByRole('link', { name: 'Войти в NEUROMIX' })).toBeInTheDocument()
  expect(screen.queryByText('my picture')).not.toBeInTheDocument()
  expect(actorReads).toBeGreaterThan(1)
})

test('a linked website session can enter its existing paid Telegram studio through verified login', async () => {
  render(<BrowserAccountWorkspace />)
  const open = await screen.findByRole('link', { name: 'Открыть привязанную студию' })
  expect(open).toHaveAttribute('href', '/login')
  expect(screen.getByText(/доступны генерация и баланс Telegram/i)).toBeInTheDocument()
})

test('an independent web account is not shown a false Telegram-wallet checkout', async () => {
  mockFetch.mockImplementation(async (input: string) => {
    const url = String(input)
    return { ok: true, status: 200, json: async () =>
      url.includes('/actor') ? { ...responses.actor, telegram_linked: false } :
      url.includes('/catalog') ? responses.catalog :
      { ...responses.history, scope: 'web_only', recent_tasks: [] },
    }
  })
  render(<BrowserAccountWorkspace />)
  expect(await screen.findByText('Nano Banana Pro')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Открыть привязанную студию' })).not.toBeInTheDocument()
  expect(screen.getByText(/Платная генерация для независимых веб-аккаунтов/i)).toBeInTheDocument()
})
