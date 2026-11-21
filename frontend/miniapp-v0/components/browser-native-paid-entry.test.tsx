import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BrowserNativePaidEntry } from './browser-native-paid-entry'

jest.mock('./web-generation-panel', () => ({
  WebGenerationPanel: () => <div>Веб-генератор готов</div>,
}))
jest.mock('./web-payments-panel', () => ({
  WebPaymentsPanel: () => <div>Пополнение веб-кошелька готово</div>,
}))
jest.mock('./web-omni-assets-panel', () => ({
  WebOmniAssetsPanel: () => <div>Создание Audio ID доступно</div>,
}))

const initialFetch = global.fetch
afterEach(() => { global.fetch = initialFetch })

const task = {
  task_id: 'web_' + 'a'.repeat(32), status: 'completed', type: 'image',
  model: 'flux_pro', result_url: 'https://neuromixbot.com/uploads/web_results/ready.png',
  created_at_epoch: 1800000000, cost: '5',
}
const answer = (body: unknown, status = 200) => ({
  status, ok: status >= 200 && status < 300, json: async () => body,
})
function mockFetch(enabled: boolean) {
  const calls: string[] = []
  global.fetch = jest.fn().mockImplementation(async (raw: string) => {
    const url = String(raw)
    calls.push(url)
    if (url.endsWith('/models')) return answer({ ok: true, enabled, models: [] })
    if (url.endsWith('/packages')) return answer({ ok: true, available: enabled, packages: [] })
    if (url.endsWith('/balance')) return answer({
      ok: true, scope: 'web_live', balance: {
        available: '11.5000', reserved: '2.0000', revision: 9,
      },
    })
    if (url.endsWith('/history')) return answer({
      ok: true, recent_tasks: [task], next_cursor: null,
    })
    throw new Error('Unexpected owner API: ' + url)
  }) as typeof fetch
  return calls
}

test('web-only account can start paid forms only with both verified server gates', async () => {
  const calls = mockFetch(true)
  render(<BrowserNativePaidEntry accountId={'a'.repeat(32)} telegramLinked={false} onSessionExpired={jest.fn()} />)
  expect(await screen.findByText('Веб-генератор готов')).toBeTruthy()
  expect(screen.getByText('Пополнение веб-кошелька готово')).toBeTruthy()
  expect(screen.getByText('Создание Audio ID доступно')).toBeTruthy()
  expect(screen.getByText(/11\.5000/)).toBeTruthy()
  expect(screen.getByText(/2\.0000/)).toBeTruthy()
  expect(screen.getByText('flux_pro')).toBeTruthy()
  expect(calls).toContain('/mini-app/api/web-auth/web-payments/balance')
  expect(calls).toContain('/mini-app/api/web-auth/web-generation/history')
})

test('rollback hides new money actions but preserves own balance and completed media', async () => {
  mockFetch(false)
  render(<BrowserNativePaidEntry accountId={'b'.repeat(32)} telegramLinked={false} onSessionExpired={jest.fn()} />)
  expect(await screen.findByText(/11\.5000/)).toBeTruthy()
  expect(screen.queryByText('Веб-генератор готов')).toBeNull()
  expect(screen.queryByText('Пополнение веб-кошелька готово')).toBeNull()
  expect(screen.getByText('flux_pro')).toBeTruthy()
  expect(screen.getByText(/создание новых платных задач отключено/i)).toBeTruthy()
})

test('linked Telegram browser reads original Telegram funds without duplicate checkout', async () => {
  const calls: string[] = []
  global.fetch = jest.fn().mockImplementation(async (raw: string) => {
    calls.push(String(raw))
    if (String(raw).endsWith('/web-payments/balance')) return answer({
      ok: true, scope: 'telegram_legacy',
      balance: { available: '24.1250', reserved: null, revision: null },
      precision_review: false,
    })
    throw new Error('Linked actor must not call paid web API: ' + raw)
  }) as typeof fetch
  render(<BrowserNativePaidEntry accountId={'c'.repeat(32)} telegramLinked onSessionExpired={jest.fn()} />)
  expect(await screen.findByText(/24.1250/)).toBeTruthy()
  expect(screen.getByText(/баланс Telegram/i)).toBeTruthy()
  expect(calls).toEqual(['/mini-app/api/web-auth/web-payments/balance'])
  expect(screen.queryByText('Пополнение веб-кошелька готово')).toBeNull()
  expect(screen.queryByText('Веб-генератор готов')).toBeNull()
})

test('linked legacy float residue never implies a balance migration', async () => {
  global.fetch = jest.fn().mockResolvedValue(answer({
    ok: true, scope: 'telegram_legacy',
    balance: { available: '0.3000', reserved: null, revision: null },
    precision_review: true,
  })) as typeof fetch
  render(<BrowserNativePaidEntry accountId={'d'.repeat(32)} telegramLinked onSessionExpired={jest.fn()} />)
  expect(await screen.findByText(/0.3000/)).toBeTruthy()
  expect(screen.getByText(/точности отображения/i)).toBeTruthy()
})

test('previous web funds remain visible separately after Telegram link', async () => {
  global.fetch = jest.fn().mockResolvedValue(answer({
    ok: true, scope: 'telegram_legacy',
    balance: { available: '12.1250', reserved: null, revision: null },
    held_web_balance: { available: '2.0000', reserved: '0.3000' },
    precision_review: false,
  })) as typeof fetch
  render(<BrowserNativePaidEntry accountId={'f'.repeat(32)} telegramLinked onSessionExpired={jest.fn()} />)
  expect(await screen.findByText(/12.1250/)).toBeTruthy()
  expect(screen.getByText(/2.0000 ROX/)).toBeTruthy()
  expect(screen.getByText(/зарезервировано 0.3000/)).toBeTruthy()
  expect(screen.queryByText(/14.1250/)).toBeNull()
  expect(screen.queryByText('Пополнение веб-кошелька готово')).toBeNull()
})

test('linked revoked session must revoke UI and never leak cached credits', async () => {
  const onSessionExpired = jest.fn()
  global.fetch = jest.fn().mockResolvedValue(answer({ ok: false }, 401)) as typeof fetch
  render(<BrowserNativePaidEntry accountId={'e'.repeat(32)} telegramLinked onSessionExpired={onSessionExpired} />)
  await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
  expect(screen.queryByText(/24.1250/)).toBeNull()
})

test('revoked session clears access without showing stale private money', async () => {
  const onSessionExpired = jest.fn()
  global.fetch = jest.fn().mockResolvedValue(answer({ ok: false }, 401)) as typeof fetch
  render(<BrowserNativePaidEntry accountId={'d'.repeat(32)} telegramLinked={false}
    onSessionExpired={onSessionExpired} />)
  await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
  expect(screen.queryByText('Веб-генератор готов')).toBeNull()
})


test('owner-scoped history cursor loads older web results without duplication', async () => {
  const calls: string[] = []
  const secondTask = { ...task, task_id: 'web_' + 'b'.repeat(32), model: 'seedream_55' }
  global.fetch = jest.fn().mockImplementation(async (raw: string) => {
    const url = String(raw)
    calls.push(url)
    if (url.endsWith('/models')) return answer({ ok: true, enabled: false })
    if (url.endsWith('/packages')) return answer({ ok: true, available: false })
    if (url.endsWith('/balance')) return answer({
      ok: true, balance: { available: '0.0000', reserved: '0.0000', revision: 0 },
    })
    if (url.includes('/history?cursor=')) return answer({
      ok: true, recent_tasks: [task, secondTask], next_cursor: null,
    })
    if (url.endsWith('/history')) return answer({
      ok: true, recent_tasks: [task], next_cursor: '1800000000:' + task.task_id,
    })
    throw new Error('Unexpected owner fetch ' + url)
  }) as typeof fetch
  render(<BrowserNativePaidEntry accountId={'e'.repeat(32)} telegramLinked={false} onSessionExpired={jest.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Загрузить ещё' }))
  expect(await screen.findByText('seedream_55')).toBeTruthy()
  expect(screen.getAllByText('flux_pro')).toHaveLength(1)
  expect(calls).toContain('/mini-app/api/web-auth/web-generation/history?cursor=' +
    encodeURIComponent('1800000000:' + task.task_id))
})
