import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFileSync, existsSync } from 'node:fs'
import { join, resolve, extname, sep } from 'node:path'
import { chromium } from 'playwright'

// Run after npm run build:vk. Signed-auth responses are mocked here; backend
// signature and public/admin authorization remain covered by the HTTP matrix.
test('VK root export gates unlinked users and opens for linked ordinary users', async () => {
  const root = resolve('out')
  assert.ok(existsSync(join(root, 'index.html')), 'Build the VK root export first')
  const types = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.svg': 'image/svg+xml', '.png': 'image/png' }
  const server = createServer((req, res) => {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname)
    const file = resolve(root, '.' + (pathname.endsWith('/') ? pathname + 'index.html' : pathname))
    if (!file.startsWith(root + sep) || !existsSync(file)) { res.writeHead(404).end(); return }
    res.setHeader('Content-Type', types[extname(file)] || 'application/octet-stream')
    res.end(readFileSync(file))
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  let browser
  try {
    browser = await chromium.launch({ headless: true })
    const origin = `http://127.0.0.1:${server.address().port}`
    for (const width of [430, 1280]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      const requests = []; const failedAssets = []
      await page.addInitScript(() => {
        window.__vkBridgeMessages = []
        window.addEventListener('message', event => window.__vkBridgeMessages.push(event.data))
      })
      page.on('request', req => requests.push(req.url()))
      page.on('response', res => { if (res.url().includes('/_next/') && res.status() >= 400) failedAssets.push(res.url()) })
      page.on('pageerror', error => console.error('VK root page error:', error.message))
      page.on('console', message => { if (message.type() === 'error') console.error('VK root console error:', message.text()) })
      await page.goto(origin + '/', { waitUntil: 'networkidle' })
      await page.getByText('Откройте приложение из ВКонтакте.', { exact: true }).waitFor()
      assert.equal(await page.evaluate(() => window.__vkBridgeMessages.some(message =>
        message?.type === 'vk-connect' && message?.handler === 'VKWebAppInit'
      )), true)
      assert.ok(!requests.some(url => /account-preview|telegram-web-app/.test(url)))
      assert.ok(requests.some(url => url.startsWith(origin + '/_next/')))
      assert.deepEqual(failedAssets, [])
      const logins = []; const appCredentials = []; let sessionUserId = ''
      await page.route('**/mini-app/api/**', async route => {
        const req = route.request(); const path = new URL(req.url()).pathname
        let payload = { ok: true, items: [], feed: [], prompts: [], categories: [], references: [], notifications: [] }; let status = 200
        if (path.endsWith('/session')) {
          const body = req.postDataJSON(); logins.push(body)
          assert.equal(body.platform, 'vk')
          sessionUserId = new URLSearchParams(body.launch_data).get('vk_user_id') || ''
          assert.ok(['2001', '3001'].includes(sessionUserId))
          payload = { ok: true, session_token: 's'.repeat(43), account: { id: 'test-account' } }
        } else if (path.endsWith('/me')) {
          const linked = sessionUserId === '2001'
          payload = { ok: true, account: { id: 'test-account' }, preview: {
            revision: 1, vk_app_id: 123, telegram_bot_username: 'Neuromixx_bot',
            telegram_linked: linked, linked_platforms: linked ? ['telegram', 'vk'] : ['vk'],
          } }
        } else if (path.endsWith('/logout')) {
          payload = { ok: true }
        } else if (path.endsWith('/bootstrap')) {
          const body = req.postDataJSON(); appCredentials.push(body.init_data)
          payload = {
            ...payload, telegram_id: 1001, first_name: 'VK', last_name: 'User', telegram_username: 'linked_user',
            credits: 301, is_admin: false, bot_username: 'Neuromixx_bot', referral_code: 'VKUSER',
            telegram_chat_available: false, telegram_bot_start_required: true,
            actions: [], payment_packages: [], image_models: [], video_models: [], recent_tasks: [], saved_references: [],
          }
        } else if (req.method() === 'POST') {
          const body = req.postDataJSON()
          if (body && 'init_data' in body) appCredentials.push(body.init_data)
        }
        await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) })
      })
      await page.goto(origin + '/?vk_app_id=123&vk_user_id=3001&sign=browser-test', { waitUntil: 'networkidle' })
      await page.getByRole('heading', { name: 'Свяжите аккаунты ТГ и ВК', exact: true }).waitFor()
      assert.equal(await page.getByRole('button', { name: 'Профиль', exact: true }).count(), 0)
      assert.equal(appCredentials.length, 0, 'Unlinked VK entry must not initialize the studio')
      await page.goto(origin + '/?vk_app_id=123&vk_user_id=2001&sign=browser-test', { waitUntil: 'networkidle' })
      try {
        await page.getByRole('button', { name: 'Профиль', exact: true }).waitFor()
      } catch (error) {
        console.error('VK root diagnostic', { requests, body: (await page.locator('body').innerText()).slice(0, 4000) })
        throw error
      }
      assert.ok(logins.length >= 2)
      for (const tab of ['Студия', 'Тренды', 'Фото', 'Видео', 'Астро', 'Лента', 'Сервисы', 'Профиль']) {
        assert.equal(await page.getByRole('button', { name: tab, exact: true }).count(), 1)
      }
      assert.equal(await page.getByRole('heading', { name: 'Общие аккаунты ТГ и ВК' }).count(), 0)
      assert.equal(await page.getByRole('heading', { name: 'Разреши боту писать тебе' }).count(), 0)
      assert.ok(appCredentials.length >= 1)
      assert.ok(appCredentials.every(value => value === 'vk_session:' + 's'.repeat(43)))
      assert.ok(!requests.some(url => /telegram-web-app/.test(url)))
      assert.deepEqual(failedAssets, [])
      assert.equal(await page.evaluate(() => sessionStorage.getItem('__banano_initial_search')), null)
      await context.close()
      console.log(`VK root ${width}px: public linking gate and linked ordinary user passed`)
    }
  } finally { await browser?.close(); await new Promise(resolve => server.close(resolve)) }
})

