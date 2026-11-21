import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { WebIdentityLinksCard } from '../web-identity-links-card'
import { getInitData } from '@/lib/api'

jest.mock('@/lib/api', () => ({ getInitData: jest.fn() }))

const originalFetch = global.fetch
const answer = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300, status, json: async () => body,
})
afterEach(() => {
  jest.resetAllMocks()
  global.fetch = originalFetch
})
beforeEach(() => {
  jest.mocked(getInitData).mockReturnValue('')
})

test('profile displays real Yandex/Google/email providers instead of obsolete VK and Telegram links', async () => {
  global.fetch = jest.fn().mockResolvedValue(answer({
    ok: true, authenticated: true, connected: ['telegram', 'yandex'],
    providers: { yandex: true, google: false, email: false, telegram: true },
  })) as typeof fetch
  render(<WebIdentityLinksCard />)
  expect(await screen.findByLabelText('Яндекс ID привязан')).toBeInTheDocument()
  expect(screen.getByText('Google')).toBeInTheDocument()
  expect(screen.getByText('Электронная почта')).toBeInTheDocument()
  expect(screen.queryByText('ВКонтакте')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Привязать ВКонтакте' })).not.toBeInTheDocument()
  expect(screen.getAllByText('Сервис пока не настроен')).toHaveLength(2)
  expect(screen.queryByRole('button', { name: 'Добавить почту' })).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Открыть самостоятельную веб-версию' }))
    .toHaveAttribute('href', '/login?web=1')
})

test('native Telegram signs into web auth using verified initData before showing available links', async () => {
  jest.mocked(getInitData).mockReturnValue('signed-native-launch')
  const responses = [
    answer({ ok: true, authenticated: false, connected: [],
      providers: { yandex: true, google: false, email: false } }),
    answer({ ok: true, authenticated: true }),
    answer({ ok: true, authenticated: true, connected: ['telegram'],
      providers: { yandex: true, google: false, email: false } }),
  ]
  global.fetch = jest.fn().mockImplementation(async () => responses.shift()) as typeof fetch
  render(<WebIdentityLinksCard />)
  const link = await screen.findByRole('link', { name: 'Привязать Яндекс ID' })
  expect(link).toHaveAttribute('href', '/mini-app/api/web-auth/start/yandex?intent=link&next=%2Fmini-app%2F')
  expect(global.fetch).toHaveBeenCalledWith('/mini-app/api/web-auth/native-session',
    expect.objectContaining({ method: 'POST', credentials: 'same-origin',
      body: JSON.stringify({ init_data: 'signed-native-launch' }) }))
  expect(screen.queryByRole('link', { name: /Google/ })).not.toBeInTheDocument()
})

test('email linking sends existing email OTP with link intent and verifies one-time code', async () => {
  let linked = false
  const urls: string[] = []
  global.fetch = jest.fn().mockImplementation(async (url: string) => {
    urls.push(url)
    if (url.endsWith('/config')) return answer({
      ok: true, authenticated: true, connected: linked ? ['telegram', 'email'] : ['telegram'],
      providers: { yandex: true, google: false, email: true },
    })
    if (url.endsWith('/email/start')) return answer({
      ok: true, challenge_id: 'a'.repeat(43), message: 'Код отправлен',
    })
    if (url.endsWith('/email/verify')) {
      linked = true
      return answer({ ok: true, redirect: '/login?linked=email' })
    }
    throw new Error('Unexpected ' + url)
  }) as typeof fetch
  render(<WebIdentityLinksCard />)
  fireEvent.click(await screen.findByRole('button', { name: 'Добавить почту' }))
  fireEvent.change(screen.getByLabelText('Адрес электронной почты'), {
    target: { value: 'user@example.com' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Отправить код' }))
  expect(await screen.findByText('Код отправлен')).toBeInTheDocument()
  expect(global.fetch).toHaveBeenCalledWith('/mini-app/api/web-auth/email/start',
    expect.objectContaining({ body: JSON.stringify({
      email: 'user@example.com', intent: 'link', next: '/mini-app/',
    }) }))
  fireEvent.change(screen.getByLabelText('Код из письма'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: 'Подтвердить почту' }))
  expect(await screen.findByLabelText('Электронная почта привязана')).toBeInTheDocument()
  expect(global.fetch).toHaveBeenCalledWith('/mini-app/api/web-auth/email/verify',
    expect.objectContaining({ body: JSON.stringify({
      challenge_id: 'a'.repeat(43), code: '123456',
    }) }))
  expect(urls.filter(url => url.endsWith('/config'))).toHaveLength(2)
})

test('different browser account is never replaced by Telegram without explicit consent', async () => {
  jest.mocked(getInitData).mockReturnValue('signed-native-launch')
  global.fetch = jest.fn().mockImplementation(async (url: string) => {
    if (url.endsWith('/config')) return answer({
      ok: true, authenticated: false, providers: { yandex: true },
    })
    return answer({ ok: false, error: 'different_web_account' }, 409)
  }) as typeof fetch
  render(<WebIdentityLinksCard />)
  expect(await screen.findByText(/открыт другой аккаунт/i)).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /Привязать/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Повторить проверку' })).toBeInTheDocument()
})


test('native owner is reverified even with a previous authenticated browser cookie', async () => {
  jest.mocked(getInitData).mockReturnValue('real-native-launch')
  global.fetch = jest.fn().mockImplementation(async (url: string) => {
    if (url.endsWith('/config')) return answer({
      ok: true, authenticated: true, connected: ['yandex'],
      providers: { yandex: true, google: false, email: false },
    })
    if (url.endsWith('/native-session')) return answer({ ok: false }, 409)
    throw new Error('Unexpected ' + url)
  }) as typeof fetch
  render(<WebIdentityLinksCard />)
  expect(await screen.findByText(/открыт другой аккаунт/i)).toBeInTheDocument()
  expect(screen.queryByLabelText('Яндекс ID привязан')).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Привязать Яндекс ID' })).not.toBeInTheDocument()
})


test('native Telegram opens the web-only URL externally instead of reusing signed WebView', async () => {
  const openLink = jest.fn()
  const previous = window.Telegram
  window.Telegram = { WebApp: { openLink } } as typeof window.Telegram
  global.fetch = jest.fn().mockResolvedValue(answer({
    ok: true, authenticated: true, connected: ['telegram'],
    providers: { yandex: true, google: false, email: false },
  })) as typeof fetch
  try {
    render(<WebIdentityLinksCard />)
    const link = await screen.findByRole('link', { name: 'Открыть самостоятельную веб-версию' })
    fireEvent.click(link)
    expect(openLink).toHaveBeenCalledWith(new URL('/login?web=1', window.location.origin).href)
  } finally {
    window.Telegram = previous
  }
})
