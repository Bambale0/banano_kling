import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFileSync, existsSync } from 'node:fs'
import { join, resolve, extname, sep } from 'node:path'
import { chromium } from 'playwright'

// Run after npm run build:vk. Signed-auth responses are mocked here; backend
// signature and public/admin authorization remain covered by the HTTP matrix.
test('VK root keeps linked and unlinked actors outside incomplete full shell', async () => {
  const root = resolve('out')
  assert.ok(existsSync(join(root, 'index.html')), 'Build the VK root export first')
  const types = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.svg': 'image/svg+xml', '.png': 'image/png' }
  const server = createServer((req, res) => {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname)
    const file = resolve(root, '.' + (pathname.endsWith('/') ? pathname + 'index.html' : pathname))
    if (!file.startsWith(root + sep) || !existsSync(file)) { res.writeHead(404).end(); return }
    res.setHeader('Content-Type', types[extname(file)] || 'application/octet-stream')
    const data = readFileSync(file)
    if (pathname === '/' && new URL(req.url, 'http://localhost').searchParams.has('test_strip_vk_query')) {
      // Only the test server simulates VK rewriting the URL after the early
      // snapshot but before the React bundle hydrates. No production rewrite.
      const html = data.toString().replace('</script>', '</script><script id="test-strip-vk-query">history.replaceState({},"","/?ref=bot_keyboard")</script>')
      assert.notEqual(html, data.toString())
      res.end(html)
    } else {
      res.end(data)
    }
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
      await page.getByRole('heading', { name: 'Вход в NEUROMIX', exact: true }).waitFor()
      const vkLogin = page.getByRole('link', { name: 'Войти через ВКонтакте', exact: true })
      assert.equal(await vkLogin.getAttribute('href'), '/mini-app/api/account-preview/vk-login')
      assert.equal(await vkLogin.getAttribute('target'), '_top')
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
            revision: 1, vk_app_id: 123, vk_community_id: 239915802, telegram_bot_username: 'Neuromixx_bot',
            telegram_linked: linked, linked_platforms: linked ? ['telegram', 'vk'] : ['vk'],
            // The true ten-domain native gateway is not registered in this test.
            full_app_ready: false,
          } }
        } else if (path.endsWith('/vk-native-state')) {
          payload = { ok: true, registered: true, balance: 13, is_blocked: false, tasks: [
            { task_id: 42, task_type: 'photo', model: 'nano_banana_pro', status: 'completed',
              cost: 2, result_url: 'https://example.test/result.jpg', created_at: '2026-11-09 12:00:00' },
          ] }
        } else if (path.endsWith('/vk-commerce')) {
          payload = { ok: true, registered: true, balance: 13,
            payments_enabled: false, payment_packages: [], payments: [],
            referrals: { first_level_count: 0, second_level_count: 0, earned_rub: 0 } }
        } else if (path.endsWith('/trends')) {
          const params = new URL(req.url()).searchParams
          if (params.get('view') === 'feed') {
            payload = { ok: true, can_generate_in_app: false, items: [{
              id: 9, generation_type: 'image', preview_url: null,
              result_url: null, likes_count: 4,
            }] }
          } else if (params.get('view') === 'category') {
            payload = { ok: true, can_generate_in_app: false, has_more: false, page: 1,
              category: { id: 77, title: 'Портреты', emoji: '🎨' },
              items: [{ id: 8, title: 'Вечерний портрет', description: '',
                preview_url: null, preview_poster_url: null, generation_type: 'image' }] }
          } else {
            payload = { ok: true, can_generate_in_app: false, categories: [{
              id: 77, title: 'Портреты', emoji: '🎨', total: 30,
              items: [{ id: 7, title: 'Портрет в стиле кино', description: '',
                preview_url: null, preview_poster_url: null, generation_type: 'image' }],
            }] }
          }
        } else if (path.endsWith('/logout')) {
          payload = { ok: true }
        } else if (path.endsWith('/bootstrap')) {
          // A signed VK actor must never receive a fabricated Telegram ID.
          const body = req.postDataJSON(); appCredentials.push(body.init_data)
          status = 503
          payload = { ok: false, error: 'VK native full adapter incomplete' }
        } else if (req.method() === 'POST') {
          const body = req.postDataJSON()
          if (body && 'init_data' in body) appCredentials.push(body.init_data)
        }
        await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) })
      })
      await page.goto(origin + '/?vk_app_id=123&vk_user_id=3001&sign=browser-test', { waitUntil: 'networkidle' })
      await page.getByRole('heading', { name: 'Создавайте в ВКонтакте', exact: true }).waitFor()
      const nativeChat = page.getByRole('link', { name: 'Генерировать в боте ВКонтакте', exact: true })
      assert.equal(await nativeChat.getAttribute('href'), 'https://vk.com/im?sel=-239915802')
      // VK-only actors now share the same visible seven-tab nav, but the
      // backend still denies Telegram-only routes and unready paid domains.
      const navigation = page.getByRole('navigation', { name: 'Разделы приложения' })
      assert.equal(await navigation.locator('button').count(), 7)
      assert.equal(await page.getByRole('button', { name: 'Motion', exact: true }).count(), 0)
      assert.equal(await page.getByRole('button', { name: 'Профиль', exact: true }).count(), 1)
      await page.getByText('VK-баланс: 13 🍌', { exact: true }).waitFor()
      await page.getByRole('button', { name: 'Профиль', exact: true }).click()
      assert.equal(await page.getByRole('link', { name: 'Открыть результат #42' })
        .getAttribute('href'), 'https://example.test/result.jpg')
      await page.getByRole('button', { name: 'Тренды', exact: true }).click()
      await page.getByText('Портрет в стиле кино', { exact: true }).waitFor()
      await page.getByRole('button', { name: 'Все (30)' }).click()
      await page.getByText('Вечерний портрет', { exact: true }).waitFor()
      await page.getByRole('button', { name: '← Ко всем трендам' }).click()
      await page.getByText('Портрет в стиле кино', { exact: true }).waitFor()
      await page.getByRole('button', { name: 'Лента', exact: true }).click()
      await page.getByText('🖼 Фото · ❤ 4', { exact: true }).waitFor()
      assert.equal(appCredentials.length, 0, 'Unlinked VK entry must not initialize the Telegram studio')
      await page.goto(origin + '/?vk_app_id=123&vk_user_id=2001&sign=browser-test', { waitUntil: 'networkidle' })
      await page.getByRole('heading', { name: 'Создавайте в ВКонтакте', exact: true }).waitFor()
      assert.ok(logins.length >= 2)
      assert.equal(await page.getByRole('button', { name: 'Профиль', exact: true }).count(), 1,
        'Linked VK and VK-only actors share the same native seven-tab navigation')
      const linkedNativeChat = page.getByRole('link', { name: 'Генерировать в боте ВКонтакте', exact: true })
      assert.equal(await linkedNativeChat.getAttribute('href'), 'https://vk.com/im?sel=-239915802')
      await page.getByRole('button', { name: 'Профиль', exact: true }).click()
      await page.getByText('VK-баланс: 13 🍌', { exact: true }).waitFor()
      assert.equal(appCredentials.length, 0, 'No VK actor may bootstrap the Telegram legacy wallet')
      assert.ok(!requests.some(url => /telegram-web-app/.test(url)))
      assert.deepEqual(failedAssets, [])
      assert.equal(await page.evaluate(() => sessionStorage.getItem('__banano_initial_search')), null)
      const loginCountBeforeStrip = logins.length
      await page.goto(origin + '/?vk_app_id=123&vk_user_id=3001&vk_ts=1794400000&sign=browser-test&test_strip_vk_query=1', { waitUntil: 'networkidle' })
      await page.getByRole('heading', { name: 'Создавайте в ВКонтакте', exact: true }).waitFor()
      assert.equal(await page.evaluate(() => window.location.search), '?ref=bot_keyboard')
      assert.equal(logins.length, loginCountBeforeStrip + 1)
      assert.equal(logins.at(-1).platform, 'vk')
      assert.ok(logins.at(-1).launch_data.includes('vk_user_id=3001'))
      assert.ok(logins.at(-1).launch_data.includes('sign=browser-test'))
      assert.equal(await page.evaluate(() => sessionStorage.getItem('__banano_initial_search')), null)
      await context.close()
      console.log(`VK root ${width}px: native fallback and linked readiness isolation passed`)
    }
  } finally { await browser?.close(); await new Promise(resolve => server.close(resolve)) }
})

