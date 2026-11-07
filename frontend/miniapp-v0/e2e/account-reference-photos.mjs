import assert from 'node:assert/strict'
import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, resolve, sep } from 'node:path'
import { chromium } from 'playwright'

// Real exported VK-only UI; synthetic HTTP/media only, no provider or wallet.
const root = resolve('out')
const mount = process.env.E2E_APP_PATH || '/mini-app/'
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' }
const server = createServer(async (request, response) => {
  const path = decodeURIComponent(new URL(request.url, 'http://localhost').pathname)
  const relative = path.startsWith(mount) ? path.slice(mount.length) : path.slice(1)
  let file = resolve(root, relative || 'index.html')
  if (!file.startsWith(root + sep)) { response.writeHead(403).end(); return }
  try {
    if ((await stat(file)).isDirectory()) file = resolve(file, 'index.html')
    await stat(file)
    response.writeHead(200, { 'Content-Type': types[extname(file)] || 'application/octet-stream' })
    createReadStream(file).pipe(response)
  } catch { response.writeHead(404).end() }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}${mount}`
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jK1sAAAAASUVORK5CYII=', 'base64')
const photo = { id: 'a'.repeat(32), mime: 'image/png', width: 1, height: 1, size_bytes: png.length, created_at_epoch: 123 }
let browser
try {
  browser = await chromium.launch({ headless: true, channel: process.env.E2E_BROWSER_CHANNEL || undefined })
  for (const width of [320, 430]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage()
    page.setDefaultTimeout(15000)
    const errors = [], calls = [], tokens = new Set()
    let saved = false, brokenThumbnail = false, linked = false, uploads = 0, deletions = 0, counter = 0
    page.on('pageerror', error => errors.push(error.message))
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'text/javascript', body: '// synthetic SDK' })
      assert.equal(url.origin, new URL(base).origin, 'No external service may be reached')
      if (!url.pathname.includes('/mini-app/api/')) return route.continue()
      calls.push(url.pathname)
      if (!url.pathname.includes('/account-preview/')) {
        assert.ok(linked, 'VK-only photos never call legacy Mini App APIs')
        const empty = { ok: true, items: [], feed: [], prompts: [], notifications: [], categories: [], references: [] }
        return route.fulfill({ json: url.pathname.endsWith('/bootstrap') ? {
          ...empty, telegram_id: 1001, first_name: 'Fixture', is_admin: true, credits: 10,
          telegram_chat_available: false, telegram_bot_start_required: true, bot_username: 'fixture_bot',
          actions: [], payment_packages: [], recent_tasks: [], saved_references: [], video_models: [], image_models: [],
        } : empty })
      }
      assert.equal(url.searchParams.has('session_token'), false)
      const path = url.pathname.split('/account-preview/')[1]
      let payload = { ok: true }
      if (path === 'settings') return route.fulfill({ status: 401, json: { ok: false, error: 'Session required' } })
      else if (path === 'session') {
        assert.equal(request.postDataJSON().platform, 'vk')
        const token = String(++counter).padStart(43, 's')
        tokens.add(token)
        payload = { ok: true, session_token: token, account: { id: 'vk-only-photo-owner' } }
      } else {
        assert.ok(tokens.has(request.headers().authorization?.replace(/^Bearer /, '')), 'Private requests use an operation session')
        if (path === 'me') payload = { ok: true, account: { id: 'vk-only-photo-owner' }, preview: {
          telegram_linked: linked, linked_platforms: linked ? ['telegram', 'vk'] : ['vk'], revision: 1, vk_app_id: 123, telegram_bot_username: 'fixture_bot',
        } }
        else if (path === 'references' && request.method() === 'POST') {
          assert.match(request.headers()['content-type'], /^multipart\/form-data; boundary=/)
          assert.match(request.postData(), /name="file"; filename="private-photo.png"/)
          saved = true; uploads++
          payload = { ok: true, reference: photo }
        } else if (path === 'references') payload = { ok: true, references: saved ? [photo] : [], next_offset: null }
        else if (path === `references/${photo.id}/thumbnail`) return route.fulfill({
          contentType: brokenThumbnail ? 'text/html' : 'image/png', body: brokenThumbnail ? '<html>SPA fallback</html>' : png,
        })
        else if (path === `references/${photo.id}` && request.method() === 'DELETE') { saved = false; deletions++ }
        else assert.equal(path, 'logout', 'No unsolicited link, generation or financial mutation')
      }
      return route.fulfill({ json: payload })
    })
    const launch = base + '?vk_app_id=123&vk_user_id=2001&sign=synthetic-private-photo'
    await page.goto(launch)
    await page.getByRole('button', { name: 'Фото аккаунта', exact: true }).click()
    await page.getByText('Пока нет сохранённых фото.', { exact: true }).waitFor()
    await page.getByLabel('Добавить фото', { exact: true }).setInputFiles({ name: 'private-photo.png', mimeType: 'image/png', buffer: png })
    await page.getByText('Фото сохранено.', { exact: true }).waitFor()
    await page.getByAltText('Фото 1', { exact: true }).waitFor()
    await page.getByAltText('Фото 1', { exact: true }).evaluate(image => image.decode())
    assert.equal(await page.getByAltText('Фото 1', { exact: true }).evaluate(image => image.naturalWidth), 1)
    assert.match(await page.getByAltText('Фото 1').getAttribute('src'), /^blob:/)
    assert.equal(uploads, 1)
    brokenThumbnail = true
    await page.reload()
    await page.getByRole('button', { name: 'Фото аккаунта', exact: true }).click()
    await page.getByText('Превью временно недоступно.', { exact: true }).waitFor()
    assert.equal(await page.getByText('Пока нет сохранённых фото.', { exact: true }).count(), 0)
    brokenThumbnail = false
    await page.getByRole('button', { name: 'Повторить загрузку превью', exact: true }).click()
    await page.getByAltText('Фото 1').evaluate(image => image.decode())
    await page.getByRole('button', { name: 'Убрать из библиотеки', exact: true }).click()
    await page.getByText('Фото убрано из библиотеки.', { exact: true }).waitFor()
    await page.getByText('Пока нет сохранённых фото.', { exact: true }).waitFor()
    assert.equal(deletions, 1)
    await page.reload()
    await page.getByRole('button', { name: 'Фото аккаунта', exact: true }).click()
    await page.getByText('Пока нет сохранённых фото.', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: 'Запустить фото', exact: true }).count(), 0)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    assert.ok(calls.some(path => path.endsWith('/thumbnail')))
    linked = true
    await page.reload()
    await page.getByRole('button', { name: 'Профиль', exact: true }).click()
    await page.getByRole('button', { name: 'Фото аккаунта', exact: true }).click()
    await page.getByText('Пока нет сохранённых фото.', { exact: true }).waitFor()
    await page.getByText('Настройки общих аккаунтов', { exact: true }).click()
    await page.getByText('Откройте приложение заново для подтверждения входа.', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: 'Обновить фото', exact: true }).count(), 1)
    assert.deepEqual(errors, [])
    await context.close()
    console.log(`PASS VK ${width}px: private upload/decode/reload/HTML recovery/removal without legacy APIs; linked profile survives settings401`)
  }
} finally {
  await browser?.close()
  server.closeAllConnections()
  await new Promise(resolve => server.close(resolve))
}
