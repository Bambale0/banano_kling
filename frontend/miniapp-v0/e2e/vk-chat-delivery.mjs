import assert from 'node:assert/strict'
import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, resolve, sep } from 'node:path'
import { chromium } from 'playwright'

// Real exported VK UI; every session, result and delivery endpoint is synthetic.
const root = resolve('out'), mount = process.env.E2E_APP_PATH || '/mini-app/'
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
const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jK1sAAAAASUVORK5CYII=', 'base64')
const task = { task_id: 'owned-vk-result', feed_id: 1, type: 'image', model: 'banana_pro', model_label: 'Nano Banana Pro',
  aspect_ratio: '9:16', status: 'completed', result_url: 'https://example.test/vk-result.png',
  created_at: '2026-11-07T13:08:03Z', prompt: 'Synthetic VK portrait', prompt_preview: 'Synthetic VK portrait', cost: 1 }
let browser
try {
  browser = await chromium.launch({ headless: true, channel: process.env.E2E_BROWSER_CHANNEL || undefined })
  for (const width of [320, 430]) for (const scenario of ['permission', 'old', 'uncertain', 'link']) {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage(); page.setDefaultTimeout(15000)
    let state = scenario === 'permission' ? 'permission_required' : scenario === 'old' ? 'not_requested' : scenario === 'link' ? 'delivered' : 'uncertain'
    let posts = 0, polls = 0, tokenIndex = 0, appToken = ''
    const errors = [], tokens = new Set(), revoked = new Set()
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => {
      window.__permissionRequests = []
      window.AndroidBridge = {
        VKWebAppInit() {},
        VKWebAppAllowMessagesFromGroup(data) { window.__permissionRequests.push(JSON.parse(data)) },
      }
    })
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'text/javascript', body: '// synthetic SDK' })
      if (url.origin === 'https://example.test') return route.fulfill({ contentType: 'image/png', body: image })
      assert.equal(url.origin, new URL(base).origin, 'No external service or chat may be reached')
      if (!url.pathname.includes('/mini-app/api/')) return route.continue()
      assert.equal(url.searchParams.has('session_token'), false)
      let payload = { ok: true, items: [], feed: [], prompts: [], notifications: [], categories: [], references: [] }
      const path = url.pathname
      if (path.endsWith('/account-preview/session')) {
        assert.equal(request.postDataJSON().platform, 'vk')
        const token = String(++tokenIndex).padStart(43, 's')
        if (!appToken) appToken = token
        tokens.add(token)
        payload = { ok: true, session_token: token, account: { id: 'owned-vk-account' } }
      } else if (path.includes('/account-preview/')) {
        const token = request.headers().authorization?.replace(/^Bearer /, '')
        assert.ok(tokens.has(token), 'Operation session is required')
        if (path.endsWith('/me')) payload = { ok: true, account: { id: 'owned-vk-account' }, preview: {
          // This fixture models a future fully ready native VK adapter,
          // independently of Telegram links or legacy wallet ownership.
          full_app_ready: true, telegram_linked: false, linked_platforms: ['vk'],
          revision: 1, vk_app_id: 123, telegram_bot_username: 'fixture_bot',
        } }
        else if (path.includes('/vk-deliveries/')) {
          // VK operations may safely reuse the active signed app session.
          // The invariant is that delivery status never revokes that session,
          // invents a new actor, or exposes its bearer in the URL.
          assert.ok(tokens.has(token), 'Delivery must use a verified app session')
          assert.ok(path.endsWith('/owned-vk-result'))
          if (request.method() === 'POST') {
            posts++
            assert.deepEqual(request.postDataJSON(), {})
            assert.ok(['permission_required', 'not_requested'].includes(state), 'No uncertain resend')
            state = 'pending'
          } else if (state === 'pending' && ++polls >= 1) state = 'delivered'
          payload = { ok: true, delivery: { state, community_id: 456, can_request: ['permission_required', 'not_requested'].includes(state),
            representation: state === 'delivered' ? scenario === 'link' ? 'link' : 'photo' : null } }
        } else {
          assert.ok(path.endsWith('/logout'), 'No unsolicited account mutation')
          revoked.add(token)
        }
      } else {
        const body = request.method() === 'POST' ? request.postDataJSON() : {}
        if ('init_data' in body) assert.equal(body.init_data, 'vk_session:' + appToken)
        if (path.endsWith('/bootstrap')) payload = { ...payload, first_name: 'Fixture VK', is_admin: false, credits: 10,
          // Native VK bootstrap must not invent a Telegram account.
          telegram_chat_available: false, telegram_bot_start_required: false, bot_username: 'fixture_bot',
          actions: [], payment_packages: [], recent_tasks: [task], saved_references: [], video_models: [], image_models: [] }
        else if (path.endsWith('/task-detail')) payload = { ok: true, task }
        else if (/generate|payment|upload/.test(path)) throw new Error('No paid or generation mutation is part of delivery smoke')
      }
      return route.fulfill({ json: payload })
    })
    await page.goto(base + '?vk_app_id=123&vk_user_id=2001&sign=synthetic-delivery')
    await page.getByRole('button', { name: 'Студия', exact: true }).click()
    await page.getByRole('button', { name: /Synthetic VK portrait/ }).click()
    const panel = page.getByRole('region', { name: 'Доставка в чат ВК' })
    await panel.waitFor()
    assert.equal(posts, 0, 'Opening a result never requests a resend')
    if (scenario === 'permission') {
      await panel.getByRole('button', { name: 'Разрешить сообщения ВК', exact: true }).click()
      assert.deepEqual(await page.evaluate(() => window.__permissionRequests), [{ group_id: 456 }])
      assert.equal(posts, 0, 'Native consent cannot fabricate a delivery receipt')
      await panel.getByRole('button', { name: 'Проверить и отправить', exact: true }).click()
      await panel.getByText('Отправлено в чат ВК.', { exact: true }).waitFor()
      assert.equal(posts, 1)
    } else if (scenario === 'old') {
      await panel.getByRole('button', { name: 'Отправить в чат ВК', exact: true }).click()
      await panel.getByText('Отправлено в чат ВК.', { exact: true }).waitFor()
      assert.equal(posts, 1)
    } else if (scenario === 'uncertain') {
      await panel.getByText(/ВК не подтвердил отправку/).waitFor()
      assert.equal(await panel.getByRole('button', { name: /отправить/i }).count(), 0)
      await panel.getByRole('button', { name: 'Обновить статус', exact: true }).click()
      assert.equal(posts, 0)
    } else await panel.getByText('Ссылка на результат отправлена в чат ВК.', { exact: true }).waitFor()
    assert.equal(await panel.getByRole('link', { name: 'Открыть чат ВК', exact: true }).getAttribute('href'), 'https://vk.com/write-456')
    assert.equal(await panel.evaluate(element => element.scrollWidth > element.clientWidth), false)
    assert.deepEqual(errors, [])
    assert.equal(revoked.has(appToken), false, 'Delivery must never revoke the active VK session')
    await context.close()
    console.log(`PASS VK ${width}px ${scenario}: real result view, explicit consent/retry, truthful receipt, no provider/message calls`)
  }
} finally {
  await browser?.close()
  server.closeAllConnections()
  await new Promise(resolve => server.close(resolve))
}
