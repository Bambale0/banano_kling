import { preferredProviderForPackage } from '@/lib/contextual-topup'
import type { PaymentPackage } from '@/lib/types'

const packageWithAllMethods = {
  id: 'start', name: 'Старт', credits: 50, price_rub: 500,
  robokassa_enabled: true, freekassa_enabled: true, lava_offer_id: 'configured-offer',
} as PaymentPackage

describe('platform-aware contextual checkout provider', () => {
  it('uses only Lava for VK even when Robokassa and KASSA are configured', () => {
    expect(preferredProviderForPackage(packageWithAllMethods, 'vk')).toBe('lava_card')
  })

  it('does not offer a forbidden fallback if a VK package has no Lava offer', () => {
    expect(preferredProviderForPackage({ ...packageWithAllMethods, lava_offer_id: '' }, 'vk')).toBeNull()
  })

  it('preserves the Telegram provider ordering', () => {
    expect(preferredProviderForPackage(packageWithAllMethods)).toBe('robokassa')
  })
})
