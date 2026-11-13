import assert from 'node:assert/strict'
import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, resolve, sep } from 'node:path'
import { chromium } from 'playwright'

// Exported application code is real; every API/provider/media response is synthetic.
const root = resolve('out')
const mount = process.env.E2E_APP_PATH || '/mini-app/'
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' }
const server = createServer(async (request, response) => {
  const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname)
  const relative = pathname.startsWith(mount) ? pathname.slice(mount.length) : pathname.slice(1)
  let file = resolve(root, relative || 'index.html')
  if (file !== root && !file.startsWith(root + sep)) { response.writeHead(403).end(); return }
  try {
    if ((await stat(file)).isDirectory()) file = resolve(file, 'index.html')
    await stat(file)
    response.writeHead(200, { 'Content-Type': mime[extname(file)] || 'application/octet-stream' })
    createReadStream(file).pipe(response)
  } catch { response.writeHead(404).end() }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}${mount}`
const folder = { id: 'a'.repeat(32), name: 'Мои фото', count: 0 }
const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jK1sAAAAASUVORK5CYII=', 'base64')
const photoUrl = 'https://example.test/reference.png'
let browser
try {
  browser = await chromium.launch({ headless: true, channel: process.env.E2E_BROWSER_CHANNEL || undefined })
  for (const platform of ['telegram', 'vk'].filter(value => !process.env.E2E_PLATFORM || value === process.env.E2E_PLATFORM)) {
    const context = await browser.newContext({ viewport: { width: 430, height: 900 } })
    const page = await context.newPage()
    page.setDefaultTimeout(15000)
    const errors = []
    let generation = null
    let uploads = 0
    page.on('pageerror', error => errors.push(error.message))
    if (platform === 'telegram') await page.addInitScript(() => {
      window.Telegram = { WebApp: { initData: 'synthetic-picker-launch', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
    })
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'text/javascript', body: '// synthetic SDK' })
      if (request.url() === photoUrl) return route.fulfill({ contentType: 'image/png', body: image })
      if (!url.pathname.includes('/mini-app/api/')) {
        assert.equal(url.origin, new URL(base).origin, 'No external service may be reached')
        return route.continue()
      }
      let payload = { ok: true, items: [], feed: [], prompts: [], notifications: [], categories: [] }
      if (url.pathname.endsWith('/account-preview/session')) payload = { ok: true, session_token: 's'.repeat(43), account: { id: 'picker-account' } }
      if (url.pathname.endsWith('/account-preview/me')) payload = { ok: true, account: { id: 'picker-account' }, preview: {
        // Positive VK-only picker scenario needs explicit signed native readiness.
        full_app_ready: platform === 'vk', telegram_linked: false,
        linked_platforms: platform === 'vk' ? ['vk'] : ['telegram'],
        revision: 1, vk_app_id: 123, telegram_bot_username: 'fixture_bot',
      } }
      if (url.pathname.endsWith('/bootstrap')) payload = {
        ...payload,
        // A native VK bootstrap must never fabricate a Telegram identity.
        ...(platform === 'telegram' ? { telegram_id: 1001 } : {}),
        first_name: 'Fixture', is_admin: false, credits: 10,
        telegram_chat_available: platform === 'telegram', telegram_bot_start_required: false,
        bot_username: 'fixture_bot',
        actions: [], payment_packages: [], recent_tasks: [], saved_references: [], video_models: [],
        image_models: [{ id: 'banana_pro', label: 'Nano Banana Pro', cost: 1, ratios: ['9:16'], max_references: 8, requires_reference: false }],
      }
      if (url.pathname.endsWith('/reference-library')) {
        const body = request.postDataJSON()
        payload = body.action === 'categories' ? { ok: true, categories: [folder], recent: [] } : { ok: true, items: [], next_offset: null }
      }
      if (url.pathname.endsWith('/upload')) {
        uploads++
        payload = { ok: true, url: photoUrl, kind: 'image', filename: 'reference.png', reference: null }
      }
      if (url.pathname.endsWith('/generate-image')) {
        generation = request.postDataJSON()
        // Stop at the public request seam: no task, debit or paid provider call.
        return route.fulfill({ status: 400, json: { ok: false, error: 'Проверьте выбранный формат.' } })
      }
      return route.fulfill({ json: payload })
    })
    await page.goto(platform === 'vk' ? base + '?vk_app_id=123&vk_user_id=2001&sign=fixture' : base)
    await page.getByRole('button', { name: 'Фото', exact: true }).click()
    await page.getByText('Только по описанию', { exact: true }).waitFor()
    await page.getByPlaceholder('Опишите сцену, стиль, свет, камеру, детали персонажей и желаемый результат...').fill('Preserve the uploaded person')
    await page.getByRole('button', { name: 'Мои референсы', exact: true }).click()
    await page.getByRole('button', { name: 'Мои фото (0)', exact: true }).click()
    await page.getByLabel('Загрузить и выбрать').setInputFiles({ name: 'reference.png', mimeType: 'image/png', buffer: image })
    await page.getByRole('dialog').waitFor({ state: 'hidden' })
    await page.getByText('По описанию и фото', { exact: true }).waitFor()
    assert.equal(uploads, 1)
    await page.getByRole('button', { name: 'Запустить фото', exact: true }).click()
    await page.getByText('Проверьте выбранный формат.', { exact: true }).waitFor()
    assert.deepEqual(generation.reference_images, [photoUrl])
    assert.equal(generation.init_data.startsWith('vk_session:'), platform === 'vk')
    assert.equal(await page.getByText('reference.png', { exact: true }).count(), 1, 'A rejected generation retains the chosen photo')
    assert.deepEqual(errors, [])
    console.log(`PASS ${platform} category upload -> selected reference -> generation HTTP payload`)
    await context.close()
  }
} finally {
  await browser?.close()
  server.closeAllConnections()
  await new Promise(resolve => server.close(resolve))
}
