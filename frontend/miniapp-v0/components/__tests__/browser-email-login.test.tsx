import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { EmailCodeLogin, standaloneWebStudioDestination, emailVerificationDestination } from '../landing-login-panel'

jest.mock('@/components/magicui/noise-texture', () => ({ NoiseTexture: () => null }))
jest.mock('@/lib/api', () => ({ getInitData: () => '' }))
const send = jest.fn()
beforeEach(() => {
  send.mockReset()
  global.fetch = send
})

test('email OTP is posted to native web-auth service without a Telegram ID', async () => {
  send.mockResolvedValueOnce({ status: 200, ok: true, json: async () => ({
    ok: true, challenge_id: 'challenge-server-owned', message: 'Код отправлен',
  }) })
  render(<EmailCodeLogin />)
  fireEvent.change(screen.getByLabelText('Войти по электронной почте'), { target: { value: 'user@example.com' } })
  fireEvent.click(screen.getByRole('button', { name: 'Получить код' }))
  expect(await screen.findByText('Код отправлен')).toBeInTheDocument()
  const [path, options] = send.mock.calls[0]
  expect(path).toBe('/mini-app/api/web-auth/email/start')
  expect(options.credentials).toBe('same-origin')
  expect(options.cache).toBe('no-store')
  expect(JSON.parse(options.body)).toEqual({ email: 'user@example.com', next: '/login' })
  expect(screen.getByLabelText('Код из письма')).toHaveAttribute('maxLength', '6')
})

test('email OTP failure keeps the form and renders a retryable error', async () => {
  send.mockResolvedValueOnce({ status: 429, ok: false, json: async () => ({ ok: false }) })
  render(<EmailCodeLogin />)
  fireEvent.change(screen.getByLabelText('Войти по электронной почте'), { target: { value: 'user@example.com' } })
  fireEvent.click(screen.getByRole('button', { name: 'Получить код' }))
  expect(await screen.findByText(/Не удалось отправить код/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Получить код' })).not.toBeDisabled()
  await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
})

test('OAuth callback preserves only bounded referral parameters in the web studio route', () => {
  expect(standaloneWebStudioDestination('?ref=FOO_25&startapp=ref_bar')).toBe(
    '/mini-app/?web=1&ref=FOO_25&startapp=ref_bar',
  )
  expect(standaloneWebStudioDestination('?ref=bad%2Fpath&startapp=%2F%2Fevil.example')).toBe(
    '/mini-app/?web=1',
  )
  expect(standaloneWebStudioDestination('?return_to=https%3A%2F%2Fevil.example')).toBe(
    '/mini-app/?web=1',
  )
})

test('verified email returns to server-approved local login for account-aware routing', () => {
  expect(emailVerificationDestination('/login?startapp=promo_123')).toBe('/login?startapp=promo_123')
  expect(emailVerificationDestination('/login?return_to=%2Fmini-app%2F%3Fintent%3Dtopup')).toBe(
    '/login?return_to=%2Fmini-app%2F%3Fintent%3Dtopup',
  )
  expect(emailVerificationDestination('/mini-app/?web=1')).toBe('/mini-app/?web=1')
  for (const unsafe of [
    'https://evil.example/login', '//evil.example/path', '/\\evil.example', '/landing',
    '/login#secret', '/login\n', '/mini-app/../admin',
  ]) {
    expect(emailVerificationDestination(unsafe)).toBe('/login')
  }
})
