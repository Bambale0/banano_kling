import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { TelegramBotApprovalLogin } from './telegram-bot-approval-login'

const ROOT = '/mini-app/api/web-auth/telegram-approval'
const originalFetch = global.fetch

function syntheticApproval() {
  return {
    ok: true,
    id: 'a'.repeat(32),
    url: 'https://t.me/neuromix_test_bot?start=auth_' + 'b'.repeat(43),
    confirmation_code: '492017',
    expires_in: 300,
  }
}

beforeEach(() => {
  jest.spyOn(window, 'open').mockReturnValue(null)
})

afterEach(() => {
  global.fetch = originalFetch
  jest.restoreAllMocks()
})

test('initiates a browser-only Telegram challenge and displays the matching confirmation code', async () => {
  const requests: Array<{ path: string; options?: RequestInit }> = []
  global.fetch = jest.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    const url = String(path)
    requests.push({ path: url, options })
    if (url === ROOT + '/start') return {
      ok: true, json: async () => syntheticApproval(),
    } as Response
    if (url.startsWith(ROOT + '/status?id=')) return {
      ok: true, json: async () => ({ ok: true, status: 'pending' }),
    } as Response
    throw new Error('Unexpected request ' + url)
  }) as typeof fetch

  const view = render(<TelegramBotApprovalLogin />)
  fireEvent.click(screen.getByRole('button', { name: 'Войти через Telegram' }))
  expect(await screen.findByText('492017')).toBeTruthy()
  const link = screen.getByRole('link', { name: /Открыть Telegram/ })
  expect(link.getAttribute('href')).toBe(syntheticApproval().url)
  expect(link.getAttribute('rel')).toContain('noopener')
  const initiated = requests.find(item => item.path.endsWith('/start'))
  expect(initiated?.options).toEqual(expect.objectContaining({
    method: 'POST', credentials: 'same-origin', cache: 'no-store', body: '{}',
  }))
  expect(JSON.stringify(initiated?.options)).not.toContain('telegram_id')
  view.unmount()
})

test('cancel aborts browser polling and denies the pending request', async () => {
  const requests: Array<{ path: string; options?: RequestInit }> = []
  global.fetch = jest.fn(async (path: RequestInfo | URL, options?: RequestInit) => {
    const url = String(path)
    requests.push({ path: url, options })
    if (url === ROOT + '/start') return {
      ok: true, json: async () => syntheticApproval(),
    } as Response
    if (url.startsWith(ROOT + '/status?id=')) return {
      ok: true, json: async () => ({ ok: true, status: 'pending' }),
    } as Response
    if (url === ROOT + '/cancel') return {
      ok: true, json: async () => ({ ok: true, status: 'denied' }),
    } as Response
    throw new Error('Unexpected request ' + url)
  }) as typeof fetch

  const view = render(<TelegramBotApprovalLogin />)
  fireEvent.click(screen.getByRole('button', { name: 'Войти через Telegram' }))
  const cancel = await screen.findByRole('button', { name: 'Отменить вход' })
  fireEvent.click(cancel)
  await waitFor(() => {
    const request = requests.find(item => item.path === ROOT + '/cancel')
    expect(request).toBeTruthy()
    expect(JSON.parse(String(request?.options?.body))).toEqual({ id: 'a'.repeat(32) })
  })
  expect(screen.getByText('Запрос отменён.')).toBeTruthy()
  expect(screen.queryByText('492017')).toBeNull()
  expect(requests.some(item => item.path.endsWith('/claim'))).toBe(false)
  view.unmount()
})

test('invalid challenge response never opens an arbitrary URL or starts polling', async () => {
  global.fetch = jest.fn(async () => ({
    ok: true, json: async () => ({ ...syntheticApproval(), url: 'https://evil.example/phish' }),
  })) as unknown as typeof fetch

  render(<TelegramBotApprovalLogin />)
  fireEvent.click(screen.getByRole('button', { name: 'Войти через Telegram' }))
  expect(await screen.findByText(/Не удалось запустить подтверждение/)).toBeTruthy()
  expect(screen.queryByRole('link', { name: /Открыть Telegram/ })).toBeNull()
})
