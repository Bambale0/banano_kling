import { containsAccountLink } from '../account-launch-security'

const launch = 'start_param=link_' + 'a'.repeat(43)
test.each([launch, encodeURIComponent(launch), encodeURIComponent(encodeURIComponent(launch))])('detects raw and nested encoded invitation credentials', value => {
  expect(containsAccountLink(value)).toBe(true)
})
test('normal referral and task launches remain cacheable', () => {
  expect(containsAccountLink('start_param=feed_123_ref_CODE')).toBe(false)
})
