import { act, fireEvent, render, screen } from '@testing-library/react'
import { WebOmniAssetsPanel } from './web-omni-assets-panel'

const originalFetch = global.fetch

beforeEach(() => {
  Object.defineProperty(window.crypto, 'randomUUID', {
    configurable: true, value: () => '12345678-1234-1234-1234-123456789abc',
  })
})
afterEach(() => { global.fetch = originalFetch })

test('web-only Audio ID quote, create and owned catalog never submit raw provider ids', async () => {
  const requests: Array<{ path: string; data: Record<string, unknown> | null }> = []
  global.fetch = jest.fn().mockImplementation(async (path: string, options?: RequestInit) => {
    const body = typeof options?.body === 'string' ? JSON.parse(options.body) : null
    requests.push({ path, data: body })
    if (path.endsWith('/assets')) return {
      ok: true, json: async () => ({ ok: true, assets: [
        { asset_id: 'oa_' + '1'.repeat(32), kind: 'audio', name: 'Existing voice', created_at_epoch: 10 },
      ], base_voices: ['achernar', 'zephyr'] }),
    }
    if (path.endsWith('/quote')) return {
      ok: true, json: async () => ({ ok: true, kind: 'audio', price: '3' }),
    }
    if (path.endsWith('/create')) return {
      ok: true, json: async () => ({
        ok: true, task_id: 'web_' + 'e'.repeat(32), status: 'pending',
      }),
    }
    if (path.includes('/task/')) return {
      ok: true, json: async () => ({ ok: true, task: {
        task_id: 'web_' + 'e'.repeat(32), status: 'completed',
        asset_id: 'oa_' + 'c'.repeat(32), asset_kind: 'audio',
      } }),
    }
    throw new Error('Unexpected Omni route: ' + path)
  }) as typeof fetch

  const refresh = jest.fn()
  render(<WebOmniAssetsPanel onBalanceChanged={refresh} onTaskChanged={jest.fn()} />)
  expect(await screen.findByText(/Existing voice/)).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Имя голоса'), {
    target: { value: 'New voice' },
  })
  fireEvent.change(screen.getByLabelText('Базовый голос'), {
    target: { value: 'zephyr' },
  })
  fireEvent.change(screen.getByLabelText('Описание голоса'), {
    target: { value: 'Natural and warm tone' },
  })
  const create = await screen.findByRole('button', { name: 'Создать за 3 кредитов' })
  fireEvent.click(create)
  expect(await screen.findByRole('status')).toBeTruthy()
  const payload = requests.find(x => x.path.endsWith('/create'))?.data
  expect(payload).toEqual(expect.objectContaining({
    kind: 'audio', name: 'New voice', base_voice: 'zephyr',
    expected_price: '3',
    request_key: '12345678123412341234123456789abc',
  }))
  expect(payload?.telegram_id).toBeUndefined()
  expect(payload?.account_id).toBeUndefined()
  expect(payload?.audio_id).toBeUndefined()
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Проверить статус' }))
    await Promise.resolve()
    await Promise.resolve()
  })
  expect(await screen.findByText('ID готов и привязан к аккаунту')).toBeTruthy()
  expect(refresh).toHaveBeenCalled()
})

test('character creation requires an uploaded owned reference and quotes linked voice', async () => {
  const requests: Array<{ path: string; body: unknown }> = []
  global.fetch = jest.fn().mockImplementation(async (path: string, options?: RequestInit) => {
    const body = typeof options?.body === 'string' ? JSON.parse(options.body) : null
    requests.push({ path, body })
    if (path.endsWith('/assets')) return {
      ok: true, json: async () => ({ ok: true, assets: [
        { asset_id: 'oa_' + '2'.repeat(32), kind: 'audio', name: 'My voice', created_at_epoch: 20 },
      ], base_voices: ['achernar'] }),
    }
    if (path.endsWith('/reference')) return {
      ok: true, json: async () => ({ ok: true, reference_id: 'wr_' + 'a'.repeat(32) }),
    }
    if (path.endsWith('/quote')) return {
      ok: true, json: async () => ({ ok: true, price: '5', kind: 'character' }),
    }
    if (path.endsWith('/create')) return {
      ok: true, json: async () => ({ ok: true, task_id: 'web_' + 'b'.repeat(32) }),
    }
    throw new Error('Unexpected path: ' + path)
  }) as typeof fetch

  render(<WebOmniAssetsPanel onBalanceChanged={jest.fn()} onTaskChanged={jest.fn()} />)
  await screen.findByText(/My voice/)
  fireEvent.change(screen.getByLabelText('Тип идентификатора'), {
    target: { value: 'character' },
  })
  fireEvent.change(screen.getByLabelText('Имя персонажа'), {
    target: { value: 'Fox Hero' },
  })
  fireEvent.change(screen.getByLabelText('Описание персонажа'), {
    target: { value: 'A cheerful animated guide' },
  })
  fireEvent.change(screen.getByLabelText('Изображение персонажа'), {
    target: { files: [new File(['fake'], 'fox.png', { type: 'image/png' })] },
  })
  await screen.findByText('Загружено: fox.png')
  fireEvent.change(screen.getByLabelText('Связанный Audio ID (необязательно)'), {
    target: { value: 'oa_' + '2'.repeat(32) },
  })
  fireEvent.click(await screen.findByRole('button', { name: 'Создать за 5 кредитов' }))
  await screen.findByRole('status')
  const request = requests.find(x => x.path.endsWith('/create'))?.body as Record<string, unknown>
  expect(request).toEqual(expect.objectContaining({
    kind: 'character', character_name: 'Fox Hero',
    image_reference_id: 'wr_' + 'a'.repeat(32),
    audio_asset_ids: ['oa_' + '2'.repeat(32)],
    expected_price: '5',
  }))
})
