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

  it('prioritizes Lava.top in Telegram even when Robokassa and KASSA are configured', () => {
    expect(preferredProviderForPackage(packageWithAllMethods)).toBe('lava_card')
  })

  it('uses KASSA as the reserve when Lava is not configured, never hidden Robokassa', () => {
    expect(preferredProviderForPackage({
      ...packageWithAllMethods, lava_offer_id: '',
    })).toBe('freekassa_card')
  })

  it('uses Stars when only hidden Robokassa is configured', () => {
    expect(preferredProviderForPackage({
      ...packageWithAllMethods, lava_offer_id: '', freekassa_enabled: false,
    })).toBe('telegram_stars')
  })
})
