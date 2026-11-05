import assert from 'node:assert/strict'
import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, resolve, sep } from 'node:path'
import { chromium } from 'playwright'

const directory = resolve('out')
const types = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json', '.woff2': 'font/woff2' }
const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, 'http://localhost')
    const relative = decodeURIComponent(url.pathname).replace(/^\/mini-app\/?/, '') || 'index.html'
    let file = resolve(directory, relative)
    if (!file.startsWith(directory + sep)) throw new Error('Invalid path')
    if ((await stat(file)).isDirectory()) file = resolve(file, 'index.html')
    response.setHeader('Content-Type', types[extname(file)] || 'application/octet-stream')
    createReadStream(file).on('error', () => response.destroy()).pipe(response)
  } catch {
    response.writeHead(404).end()
  }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}/mini-app/`
let browser
try {
  browser = await chromium.launch({ headless: true })
  for (const width of [430, 1280]) {
    for (const admin of [false, true]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      page.on('pageerror', error => console.error('Preview page error:', error.message))
      page.on('console', message => { if (message.type() === 'error') console.error('Preview console error:', message.text()) })
      page.setDefaultTimeout(15000)
      const previewRequests = []
      const apiRequests = []
      const clientErrors = []
      let policy = { enabled: false, revision: 0, vk_app_id: null, vk_admin_ids: [], session_ttl_seconds: 3600, launch_max_age_seconds: 600 }
      let wallet = { scope: 'sandbox', balance: { available: '0.0000', reserved: '0.0000', revision: 0 }, entries: [], receipt: null }
      await page.addInitScript(() => {
        window.Telegram = { WebApp: { initData: 'query_id=browser-test&start_param=link_' + 'b'.repeat(43), initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
      })
      await page.route('**/telegram-web-app.js', route => route.fulfill({ contentType: 'application/javascript', body: '// deterministic bridge' }))
      await page.route('**/mini-app/api/**', async route => {
        const request = route.request()
        const path = new URL(request.url()).pathname
        apiRequests.push(path)
        if (path.endsWith('/client-log') && request.postDataJSON()?.event === 'react-error-boundary') {
          clientErrors.push(request.postDataJSON().message)
        }
        let payload = { ok: true, items: [], feed: [], prompts: [], categories: [], references: [], notifications: [] }
        if (path.endsWith('/bootstrap')) payload = {
          ...payload, telegram_id: 1001, first_name: 'Browser', last_name: 'Test', telegram_username: 'preview_test',
          credits: 10, is_admin: admin, bot_username: 'test_bot', referral_code: 'BROWSER',
          telegram_chat_available: true, telegram_bot_start_required: false,
          actions: [], payment_packages: [], image_models: [], video_models: [], recent_tasks: [], saved_references: [],
        }
        if (path.includes('/account-preview/')) {
          previewRequests.push({ path, method: request.method() })
          if (!admin) {
            await route.fulfill({ status: 403, json: { ok: false } })
            return
          }
          if (path.endsWith('/settings')) {
            if (request.method() === 'PUT') {
              const submitted = request.postDataJSON()
              assert.equal(submitted.expected_revision, policy.revision)
              policy = { ...policy, ...submitted.settings, revision: policy.revision + 1 }
            }
            payload = { ok: true, settings: policy }
          } else if (path.endsWith('/session')) {
            payload = { ok: true, session_token: 'synthetic-browser-session', account: { id: 'browser-account' } }
          } else if (path.endsWith('/me')) {
            payload = { ok: true, account: { id: 'browser-account' } }
          } else if (path.endsWith('/wallet')) {
            if (request.method() === 'POST') {
              const submitted = request.postDataJSON()
              assert.equal(submitted.amount, '0.1000')
              assert.equal(submitted.action, 'credit')
              const receipt = { operation_key: submitted.idempotency_key, kind: 'credit', amount: '0.1000', reference_key: '', sequence: 1 }
              wallet = { scope: 'sandbox', balance: { available: '0.1000', reserved: '0.0000', revision: 1 }, entries: [receipt], receipt }
            }
            payload = { ok: true, ...wallet }
          }
        }
        await route.fulfill({ json: payload })
      })
      await page.goto(base)
      await page.getByRole('button', { name: 'Профиль', exact: true }).click()
      await page.waitForFunction(() => document.body.textContent.includes('постов'))
      if (admin) {
        try {
          await page.getByLabel('Доступ администраторам').check()
        } catch (error) {
          console.error('Preview diagnostic', { apiRequests, previewRequests, body: (await page.locator('body').innerText()).slice(0, 4000) })
          throw error
        }
        await page.getByRole('button', { name: 'Сохранить доступ', exact: true }).click()
        await page.getByText('Настройки сохранены.', { exact: true }).waitFor()
        await page.getByText('Доступно: 0.0000', { exact: true }).waitFor()
        await page.getByLabel('Тестовая сумма').fill('0.1000')
        await page.getByRole('button', { name: 'Выполнить проверку', exact: true }).click()
        await page.getByText('Доступно: 0.1000', { exact: true }).waitFor()
        await page.getByRole('button', { name: 'Проверить вход', exact: true }).click()
        await page.getByText('Вход подтверждён.', { exact: true }).waitFor()
        assert(previewRequests.some(request => request.path.endsWith('/logout')))
      } else {
        assert.equal(await page.getByLabel('Доступ администраторам').count(), 0)
        assert.equal(previewRequests.length, 0)
      }
      assert.equal(await page.evaluate(() => Object.values(sessionStorage).some(value => /link_[A-Za-z0-9_-]{43}/.test(value))), false, 'Invitation credentials must stay out of browser storage')
      assert.deepEqual(clientErrors, [])
      console.log(`PASS shared-account admin=${admin} width=${width}`)
      await context.close()
    }
  }
  for (const admin of [false, true]) {
    const context = await browser.newContext({ viewport: { width: 430, height: 900 } })
    const page = await context.newPage()
    page.setDefaultTimeout(15000)
    const requests = []
    const token = 'a'.repeat(43)
    let link = { id: 'browser-link', state: 'awaiting_confirmation', revision: 1,
      expires_at_epoch: 9999999999, source_confirmed: false, target_confirmed: false,
      source_identity: { platform: 'telegram', external_id: '999999999' },
      target_identity: { platform: 'vk', external_id: '2001' } }
    await page.route('**/telegram-web-app.js', route => route.fulfill({ contentType: 'application/javascript', body: '// deterministic bridge' }))
    await page.route('**/mini-app/api/**', async route => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      requests.push(path)
      assert(!path.endsWith('/bootstrap'), 'VK entry must not initialize Telegram bootstrap')
      if (!admin) return route.fulfill({ status: 403, json: { ok: false } })
      let payload = { ok: true }
      if (path.endsWith('/session')) {
        assert.equal(request.postDataJSON().platform, 'vk')
        payload = { ok: true, session_token: 'synthetic-vk-session', account: { id: 'vk-browser-account' } }
      } else if (path.endsWith('/me')) {
        payload = { ok: true, account: { id: 'vk-browser-account' }, preview: { revision: 1, vk_app_id: 123 } }
      } else if (path.endsWith('/wallet')) {
        payload = { ok: true, scope: 'sandbox', balance: { available: '0.0000', reserved: '0.0000', revision: 0 }, entries: [], receipt: null }
      } else if (path.endsWith('/links/accept')) {
        assert.equal(request.postDataJSON().token, token)
        payload = { ok: true, link }
      } else if (path.endsWith('/links/browser-link/confirm')) {
        assert.equal(request.postDataJSON().expected_revision, 1)
        link = { ...link, revision: 2, target_confirmed: true }
        payload = { ok: true, link }
      }
      await route.fulfill({ json: payload })
    })
    await page.goto(base + '?vk_app_id=123&vk_user_id=2001&sign=browser-fixture#link_' + token)
    if (admin) {
      await page.getByRole('main', { name: 'Проверка аккаунта ВК' }).waitFor()
      assert.equal(requests.filter(path => path.includes('/links')).length, 0, 'Opening must never accept or confirm')
      await page.getByRole('button', { name: 'Принять приглашение' }).click()
      await page.getByText('Отправитель: telegram 999999999. Получатель: vk 2001.', { exact: true }).waitFor()
      await page.getByRole('button', { name: 'Подтверждаю связь аккаунтов' }).click()
      await page.getByText('Подтверждение отправителя: ожидается. Подтверждение получателя: да.', { exact: true }).waitFor()
    } else {
      await page.getByText('Требуется доступ администратора.', { exact: true }).waitFor()
      assert.equal(await page.getByLabel('Код из ссылки').count(), 0)
      assert.equal(requests.filter(path => path.includes('/links') || path.endsWith('/wallet')).length, 0)
    }
    assert.equal(await page.evaluate(() => Object.values(sessionStorage).some(value => /link_[A-Za-z0-9_-]{43}/.test(value))), false, 'VK invitation must stay out of browser storage')
    console.log(`PASS VK entry admin=${admin} width=430`)
    await context.close()
  }

} finally {
  await browser?.close()
  server.closeAllConnections()
  await new Promise(resolve => server.close(resolve))
}
