import { normalizeMiniAppMediaUrl } from '@/lib/media-url'

describe('Mini App domain migration', () => {
  it.each([
    'tanyapi.chillcreative.ru',
    'tanyapp.xn--e1aikcel5c5a.online',
    'neuromixbot.com',
  ])('serves saved media from %s through the current origin', (host) => {
    expect(normalizeMiniAppMediaUrl(`https://${host}/uploads/feed/photo.webp?v=1#preview`))
      .toBe(`${window.location.origin}/uploads/feed/photo.webp?v=1#preview`)
  })

  it('preserves external provider URLs', () => {
    const url = 'https://provider.example/uploads/photo.webp?signature=keep'
    expect(normalizeMiniAppMediaUrl(url)).toBe(url)
  })
})
