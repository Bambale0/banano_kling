import { createPayment } from '../payment-api'
import { getInitData } from '../api'
jest.mock('../api', () => ({ getInitData: jest.fn(), getApiBasePath: () => '/mini-app/api', getStartParamFallback: () => '' }))

it.each(['query_id=tg_native', 'query_id=browser_fixture', 'query_id=webstudio_verified-session-abcdef123456'])(
  'submits configured fiat checkout directly with current credentials: %s', async initData => {
    ;(getInitData as jest.Mock).mockReturnValue(initData)
    const originalFetch = globalThis.fetch
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, text: async () => JSON.stringify({ ok: true, payment_url: 'https://checkout.synthetic.test/invoice' }) } as Response)
    globalThis.fetch = fetchMock
    try {
      await createPayment({ packageId: 'mini', provider: 'lava_card' })
      expect(fetchMock).toHaveBeenCalledWith('/mini-app/api/create-payment', expect.objectContaining({
        body: expect.stringContaining(initData), credentials: 'same-origin',
      }))
    } finally { globalThis.fetch = originalFetch }
  },
)
