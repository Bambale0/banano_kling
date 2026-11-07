// Opt-in, read-only acceptance against real deployed public media. No API mocks.
// MINIAPP_MEDIA_PATHS='["/uploads/public-example.png"]' node e2e/live-preview-media.mjs
import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const paths = JSON.parse(process.env.MINIAPP_MEDIA_PATHS || '[]')
const origins = JSON.parse(process.env.MINIAPP_MEDIA_ORIGINS || '["https://neuromixbot.com","https://vk.neuromixbot.com"]')
assert(paths.length > 0, 'Supply public PNG upload paths via MINIAPP_MEDIA_PATHS')
for (const path of paths) {
  assert(/^\/uploads\/[^?#]+\.png$/i.test(path), 'Only unsigned public PNG upload paths are accepted')
}
const browser = await chromium.launch({
  headless: true,
  ...(process.env.E2E_BROWSER_CHANNEL ? { channel: process.env.E2E_BROWSER_CHANNEL } : {}),
})
try {
  for (const origin of origins) {
    const page = await browser.newPage()
    try {
      await page.goto(origin, { waitUntil: 'domcontentloaded' })
      for (const path of paths) {
        const response = await page.request.get(origin + path, {
          headers: { Range: 'bytes=0-7' }, timeout: 20000,
        })
        assert([200, 206].includes(response.status()), 'Successful real media response')
        assert.match(response.headers()['content-type'] || '', /^image\/png\b/)
        assert.deepEqual([...((await response.body()).subarray(0, 8))], [137, 80, 78, 71, 13, 10, 26, 10])
        await response.dispose()
        const dimensions = await page.evaluate(async (source) => {
          const image = new Image()
          image.src = source
          document.body.replaceChildren(image)
          await image.decode()
          return { width: image.naturalWidth, height: image.naturalHeight }
        }, origin + path)
        assert(dimensions.width > 0 && dimensions.height > 0, 'Full image decodes in browser')
        // Never print user upload paths, signed URLs, or authentication data.
        console.log(JSON.stringify({ origin, status: response.status(), type: 'image/png', ...dimensions }))
      }
    } finally {
      await page.close()
    }
  }
} finally {
  await browser.close()
}
