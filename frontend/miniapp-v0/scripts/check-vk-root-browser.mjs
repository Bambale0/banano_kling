import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFileSync, existsSync } from 'node:fs'
import { join, resolve, extname, sep } from 'node:path'
import { chromium } from 'playwright'

// Run after npm run build:vk. Signed-auth responses are mocked here; backend
// signature/admin checks remain covered by the shared-account HTTP matrix.
test('VK root export loads assets and keeps unsigned/ordinary visitors out', async () => {
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
      page.on('request', req => requests.push(req.url()))
      page.on('response', res => { if (res.url().includes('/_next/') && res.status() >= 400) failedAssets.push(res.url()) })
      await page.goto(origin + '/', { waitUntil: 'networkidle' })
      await page.getByText('Откройте приложение из ВКонтакте.', { exact: true }).waitFor()
      assert.ok(!requests.some(url => /account-preview|telegram-web-app/.test(url)))
      assert.ok(requests.some(url => url.startsWith(origin + '/_next/')))
      assert.deepEqual(failedAssets, [])
      const logins = []
      await page.route('**/mini-app/api/account-preview/**', async route => {
        const req = route.request(); const path = new URL(req.url()).pathname
        let payload = { ok: true }; let status = 200
        if (path.endsWith('/session')) {
          const body = req.postDataJSON(); logins.push(body)
          assert.equal(body.platform, 'vk')
          if (new URLSearchParams(body.launch_data).get('vk_user_id') !== '2001') {
            status = 403; payload = { ok: false }
          } else payload = { ok: true, session_token: 'test-session', account: { id: 'test-account' } }
        } else if (path.endsWith('/me')) payload = { ok: true, account: { id: 'test-account' }, preview: { revision: 1, vk_app_id: 123, telegram_bot_username: 'Neuromixx_bot' } }
        else if (path.endsWith('/wallet')) payload = { ok: true, scope: 'sandbox', balance: { available: '0', reserved: '0', revision: 0 }, entries: [], receipt: null }
        else if (path.endsWith('/links') && req.method() === 'POST') payload = { ok: true, link: { id: 'link-1', state: 'pending', revision: 0, expires_at_epoch: 4102444800, token: 'a'.repeat(43) } }
        else if (path.endsWith('/commerce')) payload = { ok: true, catalog: { revision: 0, default_tariff_id: null, default_partner_group_id: null, tariffs: {}, partner_groups: {} } }
        else if (path.includes('/commerce/accounts/')) payload = { ok: true, target: { account_id: 'test-account', settings: { revision: 0, tariff_id: null, partner_group_id: null, first_level_percent: null, second_level_percent: null, repeat_reward_rub: null }, effective: {} } }
        await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) })
      })
      await page.goto(origin + '/?vk_app_id=123&vk_user_id=3001&sign=browser-test', { waitUntil: 'networkidle' })
      await page.getByText('Требуется доступ администратора.', { exact: true }).waitFor()
      assert.equal(await page.getByRole('heading', { name: 'Общие аккаунты ТГ и ВК' }).count(), 0)
      await page.goto(origin + '/?vk_app_id=123&vk_user_id=2001&sign=browser-test', { waitUntil: 'networkidle' })
      await page.getByRole('heading', { name: 'Общие аккаунты ТГ и ВК' }).waitFor()
      assert.ok(logins.length >= 2)
      await page.getByRole('button', { name: 'Создать ссылку' }).click()
      await page.getByLabel('Ссылка для другого аккаунта').waitFor()
      assert.equal(await page.getByLabel('Ссылка для другого аккаунта').inputValue(), `https://t.me/Neuromixx_bot?startapp=link_${'a'.repeat(43)}`)
      assert.ok(!requests.some(url => /telegram-web-app/.test(url)))
      assert.deepEqual(failedAssets, [])
      assert.equal(await page.evaluate(() => sessionStorage.getItem('__banano_initial_search')), null)
      await context.close()
      console.log(`VK root ${width}px: direct entry, ordinary denial, admin preview passed`)
    }
  } finally { await browser?.close(); await new Promise(resolve => server.close(resolve)) }
})
