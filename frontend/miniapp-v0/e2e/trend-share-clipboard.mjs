import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium, devices, webkit } from 'playwright'

// Pure browser/HTTP fixtures: no production Telegram session or paid API.
// This is the real Trends UI, not a mocked clipboard helper or a code snapshot.
const port = Number(process.env.TREND_SHARE_E2E_PORT || 4199)
const origin = `http://127.0.0.1:${port}`
const baseUrl = `${origin}/mini-app/`
const root = mkdtempSync(join(tmpdir(), 'trend-share-e2e-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const exactLink = 'https://t.me/fixture_bot/app?startapp=prompt_1606_ref_EXACT%2Bcode&mode=compact'
const trend = { id: 1606, title: 'Фото для видео тренда', description: 'Synthetic template',
  model: 'banana_pro', category: 'photo', tags: ['trend'], preview_url: null,
  prompt_text: '', uses_count: 0, likes: 0, repeat_cost: 2, author_id: 1,
  status: 'approved', generation_settings: { kind: 'image', model: 'banana_pro', user_input: 'photo', ratio: '1:1', quality: '2K' } }
let serverReady = false
let browser
try {
  const deadline = Date.now() + 20_000
  while (!serverReady) {
    try { serverReady = (await fetch(baseUrl)).ok } catch {}
    if (Date.now() > deadline) throw new Error('Static Mini App export failed to start')
    if (!serverReady) await new Promise(resolve => setTimeout(resolve, 100))
  }
  const scenarios = [
    { platform: 'ios', engine: webkit, device: 'iPhone 13', nativeShare: true },
    { platform: 'ios', engine: webkit, device: 'iPhone 13', nativeShare: false },
    { platform: 'android', engine: chromium, device: 'Pixel 7', nativeShare: false },
  ]
  for (const { platform, engine, device, nativeShare } of scenarios.filter(
    item => !process.env.TREND_SHARE_PLATFORM || item.platform === process.env.TREND_SHARE_PLATFORM,
  )) {
    browser = await engine.launch({ headless: true })
    const context = await browser.newContext({ ...devices[device] })
    const page = await context.newPage()
    page.setDefaultTimeout(20_000)
    const browserErrors = [], unexpectedMutations = []
    let linkRequests = 0
    page.on('pageerror', error => browserErrors.push(error.message))
    await context.addInitScript(({ platform, nativeShare }) => {
      window.__copyAttempts = []; window.__legacyAttempts = []; window.__nativeShares = []
      window.__opened = []; window.__legacyAllowed = false
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async value => {
        window.__copyAttempts.push(value)
        if (platform === 'ios') throw new DOMException('iOS WKWebView clipboard denied', 'NotAllowedError')
      } } })
      if (platform === 'ios' && nativeShare) {
        Object.defineProperty(navigator, 'share', { configurable: true, value: payload => {
          window.__nativeShares.push(payload); return Promise.resolve()
        } })
      } else {
        Object.defineProperty(navigator, 'share', { configurable: true, value: undefined })
      }
      document.execCommand = command => {
        if (command !== 'copy') return false
        const field = document.activeElement
        window.__legacyAttempts.push({ selected: field?.selectionStart === 0 && field?.selectionEnd === field?.value?.length, text: field?.value })
        return window.__legacyAllowed
      }
      window.Telegram = { WebApp: { platform, initData: 'query_id=synthetic-trend-share', initDataUnsafe: {},
        ready() {}, expand() {}, onEvent() {}, offEvent() {},
        openTelegramLink(url) { window.__opened.push(url) },
      } }
    }, { platform, nativeShare })
    await context.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// fixture' })
      if (url.pathname.includes('/mini-app/api/')) {
        let data = { ok: true }
        if (url.pathname.endsWith('/bootstrap')) data = {
          ok: true, telegram_id: 720005, first_name: 'Synthetic', last_name: '',
          telegram_username: 'fixture', photo_url: '', referral_code: 'FIXTURE', referral_link: '',
          profile_link: '', channel_url: '', bot_username: 'fixture_bot', credits: 200,
          prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0, is_admin: false,
          telegram_chat_available: true, mini_app_url: baseUrl, actions: [], payment_packages: [],
          image_models: [{ id: 'banana_pro', label: 'Nano Banana Pro', cost: 2, ratios: ['1:1'], max_references: 8 }],
          video_models: [], recent_tasks: [], saved_references: [],
        }
        else if (url.pathname.endsWith('/prompts')) data = { ok: true, prompts: [trend] }
        else if (url.pathname.endsWith('/prompts/link')) {
          linkRequests++
          const payload = route.request().postDataJSON()
          assert.equal(payload.prompt_id, trend.id)
          assert.equal(Object.hasOwn(payload, 'referral_code'), false, 'Referral is server-owned')
          await new Promise(resolve => setTimeout(resolve, 90)) // consume original tap activation
          data = { ok: true, link: exactLink }
        }
        else if (url.pathname.endsWith('/feed')) data = { ok: true, feed: [], models: [] }
        else if (url.pathname.endsWith('/genjutsu')) data = { ok: true, visible: false }
        else if (/generate|repeat|remix|payment|trends\/run/.test(url.pathname)) {
          unexpectedMutations.push(url.pathname)
          return route.abort('blockedbyclient')
        }
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
      }
      if (url.origin === origin) return route.continue()
      return route.abort()
    })
    await page.goto(baseUrl, { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: 'Ссылка', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Ссылка на тренд' })
    const field = dialog.getByRole('textbox', { name: 'Ссылка на тренд' })
    await field.waitFor()
    assert.equal(await field.inputValue(), exactLink)
    assert.equal(linkRequests, 1)
    assert.equal(await page.getByText('Не удалось скопировать ссылку', { exact: true }).count(), 0)
    assert.equal(await dialog.getByRole('link', { name: 'Открыть ссылку' }).getAttribute('href'), exactLink)
    const forward = dialog.getByRole('link', { name: 'Поделиться в Telegram' })
    const forwardHref = 'https://t.me/share/url?url=' + encodeURIComponent(exactLink)
    assert.equal(await forward.getAttribute('href'), forwardHref)
    await forward.click()
    assert.deepEqual(await page.evaluate(() => window.__opened), [forwardHref])
    assert.equal(linkRequests, 1)
    if (platform === 'ios') {
      await dialog.getByText(/Ссылка готова/).waitFor()
      assert.deepEqual(await page.evaluate(() => window.__copyAttempts), [], 'No clipboard attempt after API await')
      await dialog.getByRole('button', { name: 'Скопировать ссылку' }).click()
      await dialog.getByText(/Telegram не разрешил запись в буфер/).waitFor()
      assert.equal(await field.inputValue(), exactLink)
      const attempts = await page.evaluate(() => window.__legacyAttempts)
      assert.deepEqual(attempts.map(value => value.selected), [true, true], 'iOS must attempt editable field and fallback on direct tap')
      assert.deepEqual(await page.evaluate(() => window.__copyAttempts), [exactLink])
      if (nativeShare) {
        await dialog.getByRole('button', { name: 'Через меню телефона' }).click()
        assert.deepEqual(await page.evaluate(() => window.__nativeShares), [{ url: exactLink }])
      } else {
        assert.equal(await dialog.getByRole('button', { name: 'Через меню телефона' }).count(), 0)
      }
      await field.focus()
      assert.deepEqual(await field.evaluate(element => [element.selectionStart, element.selectionEnd]), [0, exactLink.length])
      await page.evaluate(() => { window.__legacyAllowed = true })
      await dialog.getByRole('button', { name: 'Скопировать ссылку' }).click()
      await dialog.getByText('Ссылка скопирована', { exact: true }).first().waitFor()
      assert.equal(await page.evaluate(() => window.__legacyAttempts.length), 3)
    } else {
      await dialog.getByText('Ссылка скопирована', { exact: true }).first().waitFor()
      assert.deepEqual(await page.evaluate(() => window.__copyAttempts), [exactLink])
    }
    assert.equal(await field.inputValue(), exactLink)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    await dialog.getByRole('button', { name: 'Close' }).click()
    await page.getByRole('button', { name: 'Фото', exact: true }).click()
    assert.equal(await page.getByRole('dialog', { name: 'Ссылка на тренд' }).count(), 0)
    assert.deepEqual(unexpectedMutations, [], 'Share must not trigger a paid generation')
    assert.deepEqual(browserErrors, [])
    console.log(`PASS ${platform}/${nativeShare ? 'native' : 'manual'}: exact referral URL, post-await safe copy, native/manual recovery, fresh tap, Telegram sharing, navigation, no paid API`)
    await context.close()
    await browser.close(); browser = undefined
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
