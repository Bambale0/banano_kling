import { render, screen } from '@testing-library/react'
import { WebAccountWorkspace } from './web-account-workspace'

const originalFetch = global.fetch
afterEach(() => { global.fetch = originalFetch })

test('renders a verified Yandex-only account without Telegram signup pressure', async () => {
  const fakeFetch = jest.fn().mockResolvedValue({
    ok: true, status: 200,
    json: async () => ({
      ok: true, account_id: '0123456789abcdef0123456789abcdef',
      studio_mode: 'web', connected: ['yandex'],
      telegram_linked: false, can_generate: false,
      balance: { available: '0.0000', reserved: '0.0000', revision: 0 },
    }),
  })
  global.fetch = fakeFetch as typeof fetch
  render(<WebAccountWorkspace />)

  await screen.findByRole('heading', { name: 'Ваш аккаунт NEUROMIX' })
  expect(screen.getByText('Яндекс ID')).toBeTruthy()
  expect(screen.getByRole('link', { name: /Связать Telegram/ }).getAttribute('href')).toBe('/login?link=telegram')
  expect(screen.getByText('0.0000')).toBeTruthy()
  expect(fakeFetch).toHaveBeenCalledWith('/mini-app/api/web-auth/account', expect.objectContaining({
    credentials: 'same-origin', cache: 'no-store',
  }))
})
