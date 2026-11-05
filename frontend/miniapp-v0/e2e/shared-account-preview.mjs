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
      await page.addInitScript(() => {
        window.Telegram = { WebApp: { initData: 'query_id=browser-test', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
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
        await page.getByRole('button', { name: 'Проверить вход', exact: true }).click()
        await page.getByText('Вход подтверждён.', { exact: true }).waitFor()
        assert(previewRequests.some(request => request.path.endsWith('/logout')))
      } else {
        assert.equal(await page.getByLabel('Доступ администраторам').count(), 0)
        assert.equal(previewRequests.length, 0)
      }
      assert.deepEqual(clientErrors, [])
      console.log(`PASS shared-account admin=${admin} width=${width}`)
      await context.close()
    }
  }
} finally {
  await browser?.close()
  server.closeAllConnections()
  await new Promise(resolve => server.close(resolve))
}
