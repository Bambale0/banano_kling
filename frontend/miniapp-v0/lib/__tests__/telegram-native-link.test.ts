import { nativeTelegramMiniAppUrl } from '../account-platform'

const token = 'a'.repeat(43)

test('turns a validated Telegram Mini App invitation into an OS-level deep link', () => {
  expect(nativeTelegramMiniAppUrl(`https://t.me/Neuromixx_bot?startapp=link_${token}`))
    .toBe(`tg://resolve?domain=Neuromixx_bot&startapp=link_${token}`)
})

test.each([
  `https://t.me.evil.example/Neuromixx_bot?startapp=link_${token}`,
  `https://evil.example/Neuromixx_bot?startapp=link_${token}`,
  `http://t.me/Neuromixx_bot?startapp=link_${token}`,
  `https://t.me/Neuromixx_bot?startapp=link_bad`,
  `https://t.me/Neuromixx_bot?startapp=link_${token}&extra=1`,
  `https://t.me/Neuromixx_bot/extra?startapp=link_${token}`,
])('refuses malformed or untrusted account invitations: %s', value => {
  expect(() => nativeTelegramMiniAppUrl(value)).toThrow('Некорректная ссылка.')
})
