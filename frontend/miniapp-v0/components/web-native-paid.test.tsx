import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { WebPaymentsPanel } from './web-payments-panel'
import { WebGenerationPanel } from './web-generation-panel'

const originalFetch = global.fetch
beforeEach(() => {
  Object.defineProperty(window.crypto, 'randomUUID', {
    configurable: true, value: () => '12345678-1234-1234-1234-123456789abc',
  })
})
afterEach(() => {
  global.fetch = originalFetch
})

test('Lava checkout uses the web session, server package price, and opaque idempotency key', async () => {
  const calls: Array<{ url: string; options: RequestInit | undefined }> = []
  global.fetch = jest.fn().mockImplementation(async (url: string, options?: RequestInit) => {
    calls.push({ url, options })
    if (url.endsWith('/packages')) return {
      ok: true, json: async () => ({ ok: true, available: true, packages: [
        { id: 'p500', name: '500 кредитов', price_rub: '500.00', credits: '550' },
      ] }),
    }
    if (url.endsWith('/create')) return {
      ok: true, json: async () => ({
        ok: true, order_id: 'web_' + 'f'.repeat(32),
        status: 'pending', amount_rub: '500.00', credits: '550',
        payment_url: 'https://gate.lava.top/payment/approved',
      }),
    }
    throw new Error('Unexpected fetch')
  }) as typeof fetch

  render(<WebPaymentsPanel onBalanceChanged={jest.fn()} />)
  await screen.findByRole('option', { name: '500 кредитов · 500.00 ₽ → 550 кредитов' })
  fireEvent.change(screen.getByLabelText('Почта для чека'), {
    target: { value: 'buyer@example.com' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Перейти к пополнению' }))
  const paymentLink = await screen.findByRole('link', { name: 'Открыть страницу оплаты Lava' })
  expect(paymentLink.getAttribute('href')).toBe('https://gate.lava.top/payment/approved')
  expect(paymentLink.getAttribute('rel')).toContain('noopener')
  const paid = calls.find(item => item.url.endsWith('/create'))
  expect(paid?.options).toEqual(expect.objectContaining({
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
  }))
  expect(JSON.parse(String(paid?.options?.body))).toEqual({
    request_key: '12345678123412341234123456789abc',
    package_id: 'p500', email: 'buyer@example.com',
  })
  expect(String(paid?.options?.body)).not.toContain('telegram_id')
})

test('web generation chooses actual catalog price, sends verified ref ID and polls durable result', async () => {
  const requests: Array<{ url: string; options?: RequestInit }> = []
  global.fetch = jest.fn().mockImplementation(async (url: string, options?: RequestInit) => {
    requests.push({ url, options })
    if (url.endsWith('/models')) return {
      ok: true, json: async () => ({ ok: true, enabled: true, models: [{
        id: 'flux_pro', label: 'GPT Image 2', type: 'image',
        price: '4.0', ratios: ['1:1', '16:9'], max_references: 4,
      }] }),
    }
    if (url.endsWith('/reference')) return {
      ok: true, json: async () => ({ ok: true, reference_id: 'wr_' + 'a'.repeat(32) }),
    }
    if (url.endsWith('/quote')) return {
      ok: true, json: async () => ({
        ok: true, model: 'flux_pro', type: 'image',
        price: '4.0', reference_count: 1, duration: 5, quality: '',
      }),
    }
    if (url.endsWith('/create')) return {
      ok: true, json: async () => ({
        ok: true, task_id: 'web_' + '1'.repeat(32), status: 'pending',
      }),
    }
    if (url.includes('/task/')) return {
      ok: true, json: async () => ({
        ok: true, task: {
          task_id: 'web_' + '1'.repeat(32), type: 'image',
          model: 'flux_pro', status: 'completed',
          result_url: 'https://neuromixbot.com/uploads/web_results/persisted.webp',
          created_at_epoch: 1800000000,
        },
      }),
    }
    throw new Error('Unexpected API call ' + url)
  }) as typeof fetch

  const refresh = jest.fn()
  const refreshTasks = jest.fn()
  render(<WebGenerationPanel onBalanceChanged={refresh} onTaskChanged={refreshTasks} />)
  await screen.findByRole('option', { name: 'GPT Image 2 (фото)' })
  expect(screen.getByRole('button', { name: 'Ожидаем расчёта цены' }).hasAttribute('disabled')).toBe(true)

  const image = new File([new Uint8Array([137, 80, 78, 71])], 'ref.png', { type: 'image/png' })
  fireEvent.change(screen.getByLabelText('Референсы (до 4 изображений)'), {
    target: { files: [image] },
  })
  await screen.findByText('ref.png')
  fireEvent.change(screen.getByLabelText('Описание'), {
    target: { value: 'Portrait with reference image' },
  })
  const createButton = await screen.findByRole('button', { name: 'Создать за 4.0 кредитов' })
  expect(createButton.hasAttribute('disabled')).toBe(false)
  fireEvent.click(createButton)
  expect(await screen.findByText('Задача: генерируется')).toBeTruthy()
  const submission = requests.find(item => item.url.endsWith('/create'))
  expect(JSON.parse(String(submission?.options?.body))).toEqual({
    request_key: '12345678123412341234123456789abc',
    model: 'flux_pro', prompt: 'Portrait with reference image',
    aspect_ratio: '1:1', duration: 5, reference_ids: ['wr_' + 'a'.repeat(32)],
    quality: undefined, expected_price: '4.0',
  })
  fireEvent.click(screen.getByRole('button', { name: 'Проверить статус' }))
  await waitFor(() => {
    expect(screen.getByRole('link', { name: 'Открыть готовый результат' })
      .getAttribute('href')).toContain('/uploads/web_results/persisted.webp')
  })
  expect(refresh).toHaveBeenCalled()
  expect(refreshTasks).toHaveBeenCalled()
})
