import { webProfileUrl, webReferralUrl, publicProfileCodeFromSearch, incomingWebReferralCode, webReferralFromPlatformLink } from '../web-public-links'

beforeEach(() => window.history.replaceState({}, '', '/mini-app/?web=1'))

test('website profile and referral links never contain Telegram or expose credentials', () => {
  expect(webProfileUrl('sel4dqap')).toBe('http://localhost/mini-app/?web=1&profile=SEL4DQAP&ref=SEL4DQAP')
  expect(webReferralUrl('sel4dqap')).toBe('http://localhost/login?web=1&ref=SEL4DQAP')
  expect(webReferralUrl('W0123ABCD9EEF')).not.toContain('t.me')
})

test('invalid public codes fail closed, never become a cross-domain redirect', () => {
  for (const value of ['', '../admin', '%2F%2Fevil.test', 'https://evil.test', 'x'.repeat(100)]) {
    expect(webProfileUrl(value)).toBe('')
    expect(webReferralUrl(value)).toBe('')
  }
})

test('public profile and referral codes survive an independent browser route', () => {
  expect(publicProfileCodeFromSearch('?web=1&profile=SEL4DQAP&ref=SEL4DQAP')).toBe('SEL4DQAP')
  expect(publicProfileCodeFromSearch('?web=1&startapp=profile_SEL4DQAP_ref_SEL4DQAP')).toBe('SEL4DQAP')
  expect(incomingWebReferralCode('?web=1&ref=w0123abcd9eef')).toBe('W0123ABCD9EEF')
  expect(incomingWebReferralCode('?web=1&ref=../bad')).toBe('')
})


test('Telegram partner link translates to a standalone web invitation without trusting other origins', () => {
  expect(webReferralFromPlatformLink('https://t.me/example_bot?start=ref_TESTCODE'))
    .toBe('http://localhost/login?web=1&ref=TESTCODE')
  expect(webReferralFromPlatformLink('https://t.me/example_bot?startapp=ref_SEL4DQAP'))
    .toBe('http://localhost/login?web=1&ref=SEL4DQAP')
  expect(webReferralFromPlatformLink('https://evil.test?startapp=ref_TESTCODE')).toBe('')
  expect(webReferralFromPlatformLink('https://t.me.evil.test/example_bot?start=ref_TESTCODE')).toBe('')
})
