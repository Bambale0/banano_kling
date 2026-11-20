import { fireEvent, render, screen } from '@testing-library/react'
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

test('verified browser identity offers optional Google/email linking and a messenger-free referral URL', async () => {
  const fetchMock = jest.fn()
    .mockResolvedValueOnce({
      ok: true, status: 200, json: async () => ({
        ok: true, account_id: '0123456789abcdef0123456789abcdef',
        studio_mode: 'web', connected: ['yandex'], telegram_linked: false,
        providers: { yandex: true, google: true, email: true },
        can_generate: false,
        balance: { available: '0.0000', reserved: '0.0000', revision: 0 },
      }),
    })
    .mockResolvedValueOnce({
      ok: true, json: async () => ({
        ok: true, url: window.location.origin + '/login?ref=NW0123456789ABCDEF',
        registrations: 2,
      }),
    })
  global.fetch = fetchMock as typeof fetch
  render(<WebAccountWorkspace />)
  expect(await screen.findByRole('link', { name: 'Связать Google' })).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Связать почту' }).getAttribute('href'))
    .toBe('/login?link=email')
  expect(await screen.findByLabelText('Веб-реферальная ссылка')).toBeTruthy()
  expect(screen.getByText('Регистраций по ссылке: 2')).toBeTruthy()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

test('web history reads only the current authenticated account and renders a real result', async () => {
  const fetchMock = jest.fn()
    .mockResolvedValueOnce({
      ok: true, status: 200, json: async () => ({
        ok: true, account_id: '0123456789abcdef0123456789abcdef',
        studio_mode: 'web', connected: ['yandex'],
        telegram_linked: false, can_generate: false,
        balance: { available: '0.0000', reserved: '0.0000', revision: 0 },
      }),
    })
    .mockResolvedValueOnce({
      ok: true, json: async () => ({ ok: false }),
    })
    .mockResolvedValueOnce({
      ok: true, json: async () => ({
        ok: true, recent_tasks: [{
          task_id: 'web_' + 'a'.repeat(32), type: 'image',
          model: 'test-image-model', status: 'completed',
          result_url: 'https://cdn.example.com/result.webp',
          created_at_epoch: 1800000000,
        }], next_cursor: null,
      }),
    })
  global.fetch = fetchMock as typeof fetch
  render(<WebAccountWorkspace />)
  await screen.findByRole('heading', { name: 'Мои веб-работы' })
  fireEvent.click(screen.getByRole('button', { name: 'Показать историю' }))
  expect(await screen.findByText('Изображение · test-image-model')).toBeTruthy()
  expect(screen.getByRole('link', { name: 'Открыть результат' }).getAttribute('href'))
    .toBe('https://cdn.example.com/result.webp')
  expect(fetchMock).toHaveBeenCalledWith('/mini-app/api/web-auth/history',
    expect.objectContaining({ credentials: 'same-origin', cache: 'no-store' }))
})
