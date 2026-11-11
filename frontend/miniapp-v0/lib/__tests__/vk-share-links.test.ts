import { platformForwardLink } from '../share-link-navigation'
import { startParamFromLocation } from '../start-params'
import { getStartParamFallback } from '../api'
import { accountLinkUrl, platformMiniAppUrl, setVerifiedVkCommunity } from '../account-platform'

describe('VK-local share links', () => {
  afterEach(() => setVerifiedVkCommunity(null, null))

  it('uses the verified server community for app shares and partner invitations', () => {
    window.history.replaceState({}, '', '/?vk_app_id=54880352&vk_user_id=2001&vk_ts=1794400000&sign=' + 'a'.repeat(43))
    setVerifiedVkCommunity(54880352, 239915802)
    expect(platformMiniAppUrl('prompt_2534')).toBe('https://vk.com/app54880352_-239915802#prompt_2534')
    expect(accountLinkUrl('vk', 'a'.repeat(43), 54880352)).toBe(
      'https://vk.com/app54880352_-239915802#link_' + 'a'.repeat(43),
    )
    // Never attach this community context to a DIFFERENT VK app ID.
    expect(accountLinkUrl('vk', 'a'.repeat(43), 123)).toBe(
      'https://vk.com/app123#link_' + 'a'.repeat(43),
    )
  })

  it('reads a VK Mini App route from the raw hash', () => {
    expect(startParamFromLocation('?vk_app_id=54880352', '#prompt_1606_ref_ABC'))
      .toBe('prompt_1606_ref_ABC')
    expect(startParamFromLocation('?vk_app_id=54880352', '#ref_ABC')).toBe('ref_ABC')
  })

  it('uses the raw VK fragment in bootstrap and profile fallbacks', () => {
    window.history.replaceState({}, '', '/?vk_app_id=54880352#profile_ABC_ref_ABC')
    expect(getStartParamFallback()).toBe('profile_ABC_ref_ABC')
    expect(platformMiniAppUrl('profile_ABC_ref_ABC', 'fixture_bot'))
      .toBe('https://vk.com/app54880352#profile_ABC_ref_ABC')
  })

  it('opens the VK share sheet instead of Telegram', () => {
    const link = 'https://vk.com/app54880352#prompt_1606_ref_ABC'
    expect(platformForwardLink(link, 'vk'))
      .toBe('https://vk.com/share.php?url=' + encodeURIComponent(link))
    expect(platformForwardLink(link, 'telegram'))
      .toBe('https://t.me/share/url?url=' + encodeURIComponent(link))
  })
})
