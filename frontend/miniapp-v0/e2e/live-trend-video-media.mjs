// Read-only real-media smoke. Supply public paths via TREND_MEDIA_SMOKE JSON:
// [{id:123,poster:'/uploads/trend-previews/catalog/....jpg',
//   clip:'/uploads/trend-previews/live/....mp4',original:'/uploads/feed/....mp4'}]
// This tests browser decoding/playback, not native iOS Telegram WebView.
import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const cards = JSON.parse(process.env.TREND_MEDIA_SMOKE || '[]')
const origin = process.env.TREND_MEDIA_ORIGIN || 'https://neuromixbot.com'
assert(cards.length > 0 && cards.length <= 12, 'Supply 1–12 published public cards')
for (const card of cards) {
  for (const key of ['poster', 'clip', 'original']) {
    assert(/^\/uploads\/[^?#]+\.(jpg|mp4)$/.test(card[key]), 'Only public unsigned media paths')
  }
}
const browser = await chromium.launch({ headless: true,
  ...(process.env.E2E_BROWSER_CHANNEL ? { channel: process.env.E2E_BROWSER_CHANNEL } : {}),
})
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await page.goto(origin + '/mini-app/', { waitUntil: 'domcontentloaded' })
  for (const card of cards) {
    for (const [key, type] of [['poster', 'image/jpeg'], ['clip', 'video/mp4'], ['original', 'video/mp4']]) {
      const response = await page.request.get(origin + card[key], {
        headers: { Range: 'bytes=0-63' }, timeout: 30000,
      })
      assert.equal(response.status(), 206, `card ${card.id} ${key}: Range must work`)
      assert((response.headers()['content-type'] || '').startsWith(type), `card ${card.id}: MIME`)
      assert.match(response.headers()['content-range'] || '', /^bytes 0-63\/\d+$/)
      const bytes = await response.body()
      assert.equal(bytes.length, 64)
      if (key === 'poster') assert.deepEqual([...bytes.subarray(0, 2)], [255, 216])
      else assert.equal(bytes.subarray(4, 8).toString(), 'ftyp')
      if (key !== 'original') assert.equal(response.url(), origin + card[key], 'Derivatives stay on origin')
      await response.dispose()
    }
    const decoded = await page.evaluate(async ({ poster, clip, original }) => {
      const bounded = (work) => Promise.race([work, new Promise((_, reject) => {
        setTimeout(() => reject(new Error('Media decode/playback timeout')), 25000)
      })])
      const image = new Image()
      image.src = poster
      await bounded(image.decode())
      const checkVideo = async (src) => {
        const video = document.createElement('video')
        video.muted = true
        video.playsInline = true
        video.src = src
        document.body.replaceChildren(video)
        try {
          await bounded(video.play())
          await bounded(new Promise((resolve, reject) => {
            const poll = setInterval(() => {
              if (video.error) { clearInterval(poll); reject(new Error('Video decode error')) }
              else if (video.currentTime > 0.25 && video.videoWidth > 0) {
                clearInterval(poll)
                resolve()
              }
            }, 50)
            setTimeout(() => { clearInterval(poll); reject(new Error('Video did not advance')) }, 24000)
          }))
          return { width: video.videoWidth, height: video.videoHeight, advanced: true }
        } finally {
          video.pause()
          video.removeAttribute('src')
          video.load()
          video.remove()
        }
      }
      return { poster: { width: image.naturalWidth, height: image.naturalHeight },
        clip: await checkVideo(clip), original: await checkVideo(original) }
    }, Object.fromEntries(['poster', 'clip', 'original'].map(key => [key, origin + card[key]])))
    console.log(JSON.stringify({ id: card.id, ...decoded }))
  }
} finally {
  await browser.close()
}
