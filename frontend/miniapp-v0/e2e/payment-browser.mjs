import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium, devices, webkit } from 'playwright'

// All APIs and payment destinations are intercepted; no live account or charge.
const root = mkdtempSync(join(tmpdir(), 'payment-browser-e2e-'))
const origin = 'http://127.0.0.1:4203'
const baseUrl = `${origin}/mini-app/`
const exactUrl = 'https://auth.robokassa.ru/Merchant/Index.aspx?InvId=9007199254740993123&Receipt=%257B%2522items%2522%253A%255B%255D%257D&SignatureValue=synthetic'
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', '4203', '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
let browser
try {
  const deadline = Date.now() + 20_000
  while (true) {
    try { if ((await fetch(baseUrl)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static Mini App unavailable')
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  const scenarios = [
    { platform: 'ios', engine: webkit, device: 'iPhone 13', bridge: 'native' },
    { platform: 'android', engine: chromium, device: 'Pixel 7', bridge: 'native' },
    { platform: 'ios', engine: webkit, device: 'iPhone 13', bridge: 'throws' },
  ]
  for (const scenario of scenarios.filter(item => !process.env.PAYMENT_BROWSER_PLATFORM || item.platform === process.env.PAYMENT_BROWSER_PLATFORM)) {
    const { platform, engine, device, bridge } = scenario
    browser = await engine.launch({ headless: true })
    const context = await browser.newContext({ ...devices[device] })
    const page = await context.newPage()
    page.setDefaultTimeout(20_000)
    let paymentRequests = 0
    const errors = [], externalRequests = []
    page.on('pageerror', error => errors.push(error.message))
    await context.addInitScript(({ platform, bridge }) => {
      window.__openedPayments = []; window.__staleOpenAttempts = 0; window.__lastTap = 0
      window.__paymentClientLogs = []
      // WebKit does not always expose sendBeacon Blob bodies through request
      // interception. Capture the actual client payload before it is sent.
      Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: (_url, data) => {
        Promise.resolve(data instanceof Blob ? data.text() : String(data)).then(body => {
          window.__paymentClientLogs.push(JSON.parse(body))
        })
        return true
      } })
      document.addEventListener('click', () => { window.__lastTap = performance.now() }, true)
      window.Telegram = { WebApp: { platform, initData: 'query_id=synthetic-payment', initDataUnsafe: {},
        ready() {}, expand() {}, onEvent() {}, offEvent() {},
        openLink(url) {
          if (bridge === 'throws') throw new Error('Synthetic bridge unavailable')
          // Telegram ignores native link events >1 second after interaction.
          if (performance.now() - window.__lastTap > 1000) { window.__staleOpenAttempts++; return }
          window.__openedPayments.push(url)
        },
      } }
    }, { platform, bridge })
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (request.url() === exactUrl) {
        externalRequests.push(request.url())
        return route.fulfill({ contentType: 'text/html', body: '<title>Synthetic checkout</title><p>Fixture payment form</p>' })
      }
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// fixture' })
      if (url.pathname.includes('/mini-app/api/')) {
        let data = { ok: true }
        if (url.pathname.endsWith('/bootstrap')) data = {
          ok: true, telegram_id: 720005, first_name: 'Synthetic', telegram_username: 'fixture',
          referral_code: 'FIXTURE', bot_username: 'fixture_bot', credits: 1, is_admin: false,
          telegram_chat_available: true, mini_app_url: baseUrl, actions: [],
          payment_packages: [{ id: 'start', name: 'Старт', credits: 50, price_rub: 500, robokassa_enabled: true }],
          image_models: [{ id: 'banana_pro', label: 'Nano Banana Pro', cost: 2, ratios: ['1:1'] }],
          video_models: [], recent_tasks: [], saved_references: [],
        }
        else if (url.pathname.endsWith('/create-payment')) {
          paymentRequests++
          const body = request.postDataJSON()
          assert.equal(body.provider, 'robokassa'); assert.equal(body.package_id, 'start')
          await new Promise(resolve => setTimeout(resolve, 1250))
          data = { ok: true, provider: 'robokassa', order_id: '9007199254740993123', payment_id: 'fixture', payment_url: exactUrl, credits: 50 }
        }
        else if (url.pathname.endsWith('/client-log')) return route.fulfill({ json: { ok: true } })
        else if (url.pathname.endsWith('/prompts')) data = { ok: true, prompts: [] }
        else if (url.pathname.endsWith('/feed')) data = { ok: true, feed: [], models: [] }
        else if (url.pathname.endsWith('/genjutsu')) data = { ok: true, visible: false }
        else if (/generate|repeat|remix|trends\/run/.test(url.pathname)) throw new Error(`Unexpected mutation: ${url.pathname}`)
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
      }
      if (url.origin === origin) return route.continue()
      return route.abort()
    })
    await page.goto(baseUrl, { waitUntil: 'networkidle' })
    await page.locator('header button').last().click()
    await page.getByRole('button', { name: 'СБП / карта', exact: true }).click()
    const proceed = page.getByRole('link', { name: 'Перейти к оплате', exact: true })
    await proceed.waitFor()
    assert.equal(await proceed.getAttribute('href'), exactUrl)
    assert.equal(page.url(), baseUrl, 'Payment must not navigate inside Mini App')
    assert.deepEqual(await page.evaluate(() => window.__openedPayments), [])
    if (platform === 'android') await page.waitForFunction(() => window.__staleOpenAttempts === 1)
    if (bridge === 'throws') {
      const popupPromise = context.waitForEvent('page')
      await proceed.click()
      const popup = await popupPromise
      await popup.waitForLoadState()
      assert.equal(popup.url(), exactUrl)
      assert.deepEqual(externalRequests, [exactUrl])
      await popup.close()
    } else {
      await proceed.click()
      await proceed.click()
      assert.deepEqual(await page.evaluate(() => window.__openedPayments), [exactUrl, exactUrl])
      assert.deepEqual(externalRequests, [])
    }
    assert.equal(paymentRequests, 1, 'Reopening must reuse the existing invoice')
    assert.equal(page.url(), baseUrl)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    assert.deepEqual(errors, [])
    await page.waitForFunction(() => window.__paymentClientLogs.some(item => item.event === 'payment-checkout-open-requested'))
    const clientLogs = await page.evaluate(() => window.__paymentClientLogs)
    assert.equal(clientLogs.some(item => item.event === 'payment-checkout-ready'), true)
    for (const log of clientLogs.filter(item => item.event.startsWith('payment-checkout'))) {
      assert.equal(JSON.stringify(log).includes('SignatureValue'), false, 'No signed URLs in telemetry')
    }
    console.log(`PASS payment browser: ${platform}, bridge=${bridge}, delayed API, exact URL, one invoice`)
    await browser.close(); browser = null
  }
} finally {
  if (browser) await browser.close()
  server.kill('SIGTERM'); rmSync(root, { recursive: true, force: true })
}
