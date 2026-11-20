import { fireEvent, render, screen } from '@testing-library/react'
import { BrowserProviderLogin, EmailCodeLogin } from './landing-login-panel'

const fetchOriginal = global.fetch
beforeEach(() => {
  window.history.replaceState({}, '', '/login')
})
afterEach(() => {
  global.fetch = fetchOriginal
  window.history.replaceState({}, '', '/login')
})

test('configured Yandex, Google and email are available without Telegram', async () => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      ok: true, authenticated: false, studio_ready: false,
      providers: { yandex: true, google: true, email: true },
    }),
  }) as typeof fetch
  render(<BrowserProviderLogin onSessionDetected={jest.fn()} />)
  expect(await screen.findByRole('link', { name: 'Продолжить с Яндекс ID' })).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Продолжить с Google' }).getAttribute('href'))
    .toBe('/mini-app/api/web-auth/start/google')
  expect(screen.getByLabelText('Адрес электронной почты')).toBeTruthy()
})

test('email account linking is permitted even when legacy Telegram studio exists', async () => {
  window.history.replaceState({}, '', '/login?link=email')
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      ok: true, authenticated: true, studio_ready: true,
      providers: { yandex: true, google: true, email: true },
    }),
  }) as typeof fetch
  render(<BrowserProviderLogin onSessionDetected={jest.fn()} />)
  expect(await screen.findByText('Привязать почту')).toBeTruthy()
  expect(global.fetch).not.toHaveBeenCalledWith(
    '/mini-app/api/web-auth/studio', expect.anything(),
  )
})

test('email code challenge starts with no token in query or storage', async () => {
  const send = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ ok: true, challenge_id: 'a'.repeat(43),
      message: 'Введите код из письма.' }),
  })
  global.fetch = send as typeof fetch
  render(<EmailCodeLogin intent="login" />)
  fireEvent.change(screen.getByLabelText('Адрес электронной почты'), {
    target: { value: 'user@example.com' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Получить код' }))
  await screen.findByLabelText('Код из письма')
  expect(send).toHaveBeenCalledWith('/mini-app/api/web-auth/email/start', expect.objectContaining({
    method: 'POST', credentials: 'same-origin',
    body: JSON.stringify({ email: 'user@example.com', intent: 'login',
      next: '/login' }),
  }))
  expect(window.location.search).toBe('')
  expect(window.sessionStorage.getItem('a'.repeat(43))).toBeNull()
})
