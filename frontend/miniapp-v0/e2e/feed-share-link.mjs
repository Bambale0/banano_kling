import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium, devices, webkit } from 'playwright'

// Android/Chromium and iOS/WebKit emulation; all APIs, clipboard and navigation
// are synthetic. No Telegram session, external destination or paid API is used.
const port = Number(process.env.FEED_SHARE_E2E_PORT || 4197)
const origin = `http://127.0.0.1:${port}`
const baseUrl = `${origin}/mini-app/`
const root = mkdtempSync(join(tmpdir(), 'feed-share-e2e-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const image = '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400"><rect width="300" height="400" fill="#334155"/></svg>'
const card = { id: 55, task_id: 'synthetic-share', model: 'banana_pro', gen_type: 'image', result_url: 'https://example.test/image.svg',
  preview_url: 'https://example.test/image.svg', result_urls: ['https://example.test/image.svg'], prompt: 'PRIVATE_RECIPE',
  prompt_hidden: true, prompt_actions_allowed: false, reference_images: [], reference_videos: [], references_hidden: true,
  likes_count: 0, shares_count: 0, comments_count: 0, author: 'Synthetic', remixes: 0, created_at: '2026-10-09T00:00:00Z' }
const links = [
  'https://t.me/fixture_bot?start=remix_55_ref_EXACT%2Bcode',
  'https://t.me/fixture_bot/app?startapp=remix_55_ref_EXACT%2Bcode&mode=compact',
]
let browser
try {
  const deadline = Date.now() + 20000
  while (true) {
    try { if ((await fetch(baseUrl)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static export unavailable')
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  for (const [name, engine, device] of [['android', chromium, 'Pixel 7'], ['ios', webkit, 'iPhone 13']]) {
    browser = await engine.launch({ headless: true })
    for (const bridge of ['present', 'absent', 'throws']) {
      const context = await browser.newContext({ ...devices[device] })
      const page = await context.newPage()
      const errors = [], destinations = [], mutationPaths = [], unexpectedApis = []
      let shareCalls = 0, exactLink = links[bridge === 'present' ? 0 : 1]
      page.on('pageerror', error => errors.push(error.message))
      await context.addInitScript(({ bridge, platform }) => {
        window.__copied = []; window.__opened = []; window.__copyAllowed = false
        window.__legacyCopies = []; window.__legacyCopyAllowed = false
        Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async value => {
          window.__copied.push(value)
          if (!window.__copyAllowed) throw new DOMException('Synthetic clipboard denial', 'NotAllowedError')
        } } })
        document.execCommand = command => {
          if (command !== 'copy') return false
          const field = document.activeElement
          window.__legacyCopies.push({ text: field?.value, selected: field?.selectionStart === 0 && field?.selectionEnd === field?.value?.length })
          return window.__legacyCopyAllowed
        }
        window.Telegram = { WebApp: { platform, initData: 'query_id=feed-share-test', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
        if (bridge !== 'absent') window.Telegram.WebApp.openTelegramLink = value => {
          if (bridge === 'throws') throw new Error('Synthetic unavailable native bridge')
          window.__opened.push(value)
        }
      }, { bridge, platform: name === 'ios' ? 'ios' : 'android' })
      await context.route('**/*', async route => {
        const url = new URL(route.request().url())
        if (url.hostname === 't.me') {
          destinations.push(route.request().url())
          return route.fulfill({ contentType: 'text/html', body: '<title>Synthetic destination</title>' })
        }
        if (url.hostname === 'example.test') return route.fulfill({ contentType: 'image/svg+xml', body: image })
        if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// fixture' })
        if (url.pathname.includes('/mini-app/api/')) {
          let data
          if (url.pathname.endsWith('/bootstrap')) data = { ok: true, telegram_id: 720003, first_name: 'Synthetic', last_name: '', telegram_username: 'synthetic',
            photo_url: '', referral_code: 'SYNTHETIC', profile_link: '', referral_link: '', channel_url: '', bot_username: 'fixture_bot', credits: 100,
            prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0, is_admin: false, telegram_chat_available: true,
            mini_app_url: baseUrl, actions: [], payment_packages: [], image_models: [{ id: 'banana_pro', label: 'Nano Banana Pro', cost: 1, ratios: ['1:1'], qualities: ['2K'], max_references: 8 }], video_models: [], recent_tasks: [], saved_references: [] }
          else if (url.pathname.endsWith('/feed/share')) { shareCalls++; data = { ok: true, feed_item: card, link: exactLink, repeat_link: exactLink } }
          else if (url.pathname.endsWith('/feed')) data = { ok: true, feed: [card], models: [{ id: 'banana_pro', label: 'Nano Banana Pro' }] }
          else if (url.pathname.endsWith('/prompts')) data = { ok: true, prompts: [] }
          else if (url.pathname.endsWith('/genjutsu') && route.request().postDataJSON()?.action === 'availability') data = { ok: true, visible: false }
          else {
            unexpectedApis.push(url.pathname)
            if (/generate|repeat|remix|payment|trends\/run/.test(url.pathname)) mutationPaths.push(url.pathname)
            return route.abort('blockedbyclient')
          }
          return route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
        }
        if (url.origin === origin) return route.continue()
        return route.abort()
      })
      await page.goto(baseUrl, { waitUntil: 'networkidle' })
      await page.getByRole('button', { name: 'Лента', exact: true }).click()
      await page.getByRole('button', { name: 'Ссылка', exact: true }).click()
      const panel = page.getByRole('region', { name: 'Ссылка на публикацию', exact: true })
      if (name === 'ios') await panel.getByText(/Ссылка готова/).waitFor()
      else await panel.getByText(/Telegram не разрешил запись в буфер/).waitFor()
      const open = panel.getByRole('link', { name: 'Открыть ссылку', exact: true })
      const field = panel.getByRole('textbox', { name: 'Ссылка на публикацию', exact: true })
      assert.equal(await field.inputValue(), exactLink)
      assert.equal(await open.getAttribute('href'), exactLink)
      assert.equal(await open.getAttribute('target'), '_blank')
      assert.equal(await open.getAttribute('rel'), 'noopener noreferrer')
      const forward = panel.getByRole('link', { name: 'Поделиться в Telegram' })
      assert.equal(await forward.getAttribute('href'), 'https://t.me/share/url?url=' + encodeURIComponent(exactLink))
      assert.equal(new URL(await forward.getAttribute('href')).searchParams.get('url'), exactLink)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      assert.equal((await page.locator('body').innerText()).includes('PRIVATE_RECIPE'), false)
      await field.focus()
      assert.deepEqual(await field.evaluate(element => [element.selectionStart, element.selectionEnd]), [0, exactLink.length])
      await open.scrollIntoViewIfNeeded()
      const box = await open.boundingBox()
      assert.ok(box && box.width >= 44 && box.height >= 44)
      mkdirSync('test-results/feed-share', { recursive: true })
      await page.screenshot({ path: `test-results/feed-share/${name}-${bridge}.png`, fullPage: true })
      if (bridge === 'present') {
        await open.click(); await open.click()
        assert.deepEqual(await page.evaluate(() => window.__opened), [exactLink, exactLink])
        assert.deepEqual(destinations, [])
      } else {
        const popupPromise = context.waitForEvent('page')
        await open.click()
        const popup = await popupPromise
        await popup.waitForLoadState('domcontentloaded')
        assert.equal(popup.url(), exactLink)
        assert.deepEqual(destinations, [exactLink])
        assert.equal(await popup.evaluate(() => window.opener), null)
        await popup.close()
      }
      assert.equal(shareCalls, 1)
      assert.equal(await page.evaluate(() => window.__copied.length), name === 'ios' ? 0 : 1)
      if (name === 'ios') {
        // Native clipboard denied; immediate textarea selection in the user's
        // second tap must work before any async permission request.
        await page.evaluate(() => { window.__legacyCopyAllowed = true })
      } else {
        await page.evaluate(() => { window.__copyAllowed = true })
      }
      await panel.getByRole('button', { name: 'Скопировать ссылку', exact: true }).click()
      await panel.getByText('Ссылка скопирована', { exact: true }).waitFor()
      if (name === 'ios') {
        assert.deepEqual(await page.evaluate(() => window.__copied), [])
        assert.deepEqual(await page.evaluate(() => window.__legacyCopies), [{ text: exactLink, selected: true }])
      } else {
        assert.deepEqual(await page.evaluate(() => window.__copied), [exactLink, exactLink])
      }
      assert.equal(shareCalls, 1)
      // Return/reopen keeps the normal feed usable; unsafe fresh responses never become executable.
      await page.getByRole('button', { name: 'Студия', exact: true }).click()
      await page.getByRole('button', { name: 'Лента', exact: true }).click()
      exactLink = 'javascript:alert(1)'
      await page.getByRole('button', { name: 'Ссылка', exact: true }).click()
      await page.waitForFunction(() => document.querySelector('input[aria-label="Ссылка на публикацию"]')?.value === 'javascript:alert(1)')
      assert.equal(await page.getByRole('link', { name: 'Открыть ссылку', exact: true }).count(), 0)
      assert.deepEqual(unexpectedApis, [], 'No unrecognized API is silently accepted')
      assert.deepEqual(mutationPaths, [])
      assert.deepEqual(errors, [])
      console.log(`PASS ${name}/${bridge}: exact URL, native/secure browser open, clipboard denial/retry, manual selection, navigation, unsafe link, no paid API`)
      await context.close()
    }
    await browser.close(); browser = undefined
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
