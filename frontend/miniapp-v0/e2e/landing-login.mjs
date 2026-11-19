import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { readFileSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'
import { once } from 'node:events'
import { chromium } from 'playwright'

const root = resolve(process.cwd(), 'out')
const artwork = resolve(process.cwd(), '../../web/landing/grunge-mobile-art-v1.webp')
const landingHtml = resolve(process.cwd(), '../../web/landing/index.html')
const posts = []
const initData = 'user=%7B%22id%22%3A123%7D&auth_date=123456&hash=browser_mock'

function json(res, status, payload) {
  const body = JSON.stringify(payload)
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) })
  res.end(body)
}

const server = createServer(async (req, res) => {
  try {
    const path = new URL(req.url || '/', 'http://127.0.0.1').pathname
    if (path === '/mini-app/api/browser-auth/config') {
      json(res, 200, { ok: true, bot_username: 'ExampleBot', oidc_client_id: '123456', oidc_nonce: 'ci-test-nonce-1234567890123456789012' })
      return
    }
    if (path === '/mini-app/api/browser-auth' && req.method === 'POST') {
      const chunks = []
      for await (const chunk of req) chunks.push(chunk)
      posts.push(JSON.parse(Buffer.concat(chunks).toString('utf8')))
      json(res, 200, { ok: true, init_data: initData })
      return
    }
    if (path === '/') {
      const data = readFileSync(landingHtml)
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(data)
      return
    }
    if (path === '/grunge-mobile-art-v1.webp') {
      const data = readFileSync(artwork)
      res.writeHead(200, { 'Content-Type': 'image/webp' })
      res.end(data)
      return
    }

    const rel = path === '/login' || path === '/login/' ? '/login/index.html'
      : path.startsWith('/mini-app/') ? path.slice('/mini-app'.length)
      : path
    const file = resolve(root, '.' + (rel === '/' ? '/index.html' : rel))
    if (file !== root && !file.startsWith(root + sep)) {
      res.writeHead(403); res.end(); return
    }
    const data = readFileSync(file)
    const type = file.endsWith('.js') ? 'text/javascript'
      : file.endsWith('.css') ? 'text/css'
      : file.endsWith('.svg') ? 'image/svg+xml'
      : file.endsWith('.html') ? 'text/html; charset=utf-8'
      : 'application/octet-stream'
    res.writeHead(200, { 'Content-Type': type, 'Content-Length': data.length })
    res.end(data)
  } catch {
    res.writeHead(404)
    res.end('Not Found')
  }
})

const telegramWidgetMock = `
(function () {
  const button = document.createElement('button');
  button.id = 'ci-telegram-login';
  button.type = 'button';
  button.textContent = 'Telegram widget mock';
  button.onclick = function () {
    window.onNeuromixLandingTelegramAuth({
      id: 123, first_name: 'Browser', auth_date: 123456, hash: 'mock_signed_payload'
    });
  };
  document.currentScript.parentElement.appendChild(button);
})();
`

let browser
try {
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const origin = `http://127.0.0.1:${server.address().port}`
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] })

  for (const [width, height] of [[320, 700], [390, 844], [768, 960], [1440, 900]]) {
    const page = await browser.newPage({ viewport: { width, height } })
    const errors = []
    let oidcOptions = null
    await page.exposeFunction('__ciTrackOidcOptions', options => { oidcOptions = options })
    page.on('pageerror', error => errors.push(String(error)))
    await page.route('https://telegram.org/js/**', route => route.fulfill({
      status: 200, contentType: 'text/javascript', body: '',
    }))
    await page.route('**/telegram-login.js', route => route.fulfill({
      status: 200, contentType: 'text/javascript', body: `
        window.Telegram = window.Telegram || {};
        window.Telegram.Login = {
          auth(options, callback) {
            window.__ciTrackOidcOptions(options);
            callback({ id_token: 'ci-id-token' });
          }
        };
      `,
    }))
    await page.route('**/telegram-widget.js?22', route => route.fulfill({
      status: 200, contentType: 'text/javascript', body: telegramWidgetMock,
    }))
    const response = await page.goto(origin + '/login' + (width === 390 ? '?startapp=test_ref&return_to=' + encodeURIComponent('/mini-app/?intent=topup&package_id=mini&provider=lava_card') : ''), {
      waitUntil: 'load',
    })
    assert.equal(response.status(), 200)
    await page.getByRole('button', { name: 'Продолжить через Telegram' }).waitFor({ state: 'visible' })
    await page.getByRole('button', { name: 'Продолжить через Telegram' }).waitFor({ state: 'visible' })
    const metrics = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      headings: document.querySelectorAll('#login-page-title').length,
      shadcn: document.querySelectorAll('[data-slot=card],[data-slot=button],[data-slot=badge],[data-slot=separator]').length,
      scripts: Array.from(document.querySelectorAll('script[src]')).filter(s => s.src.includes('/mini-app/_next/static/')).length,
    }))
    assert.ok(metrics.scrollWidth <= width + 2, `horizontal overflow at ${width}`)
    assert.equal(metrics.headings, 1)
    assert.ok(metrics.shadcn >= 4, 'shadcn UI components should render')
    assert.ok(metrics.scripts >= 2, 'Next.js bundles must load at /login')
    assert.deepEqual(errors, [], 'React/Next hydration errors')
    if (width === 390) {
      await page.getByRole('button', { name: 'Продолжить через Telegram' }).click()
      await page.waitForURL('**/mini-app/**')
      assert.ok(page.url().includes('startapp=test_ref'), 'startapp survives sign-in')
      assert.equal(new URL(page.url()).searchParams.get('intent'), 'topup')
      assert.equal(new URL(page.url()).searchParams.get('package_id'), 'mini')
      assert.equal(new URL(page.url()).searchParams.get('provider'), 'lava_card')
      assert.ok(page.url().includes('#tgWebAppData='), 'signed initData goes in URL fragment')
      assert.equal(posts.length, 1, 'a single signed login POST must be sent')
      assert.equal(posts[0].id_token, 'ci-id-token')
      assert.equal(oidcOptions?.scope?.join(','), 'profile')
      assert.equal(oidcOptions?.nonce, 'ci-test-nonce-1234567890123456789012')
    }
    await page.close()
    console.log(`login/shadcn [${width}]: OK`)
  }


  // An already authenticated browser session resumes its exact payment intent
  // without opening the new OIDC approval flow again.
  const activeSession = await browser.newPage({ viewport: { width: 390, height: 844 } })
  let activeSessionConfigRequests = 0
  activeSession.on('request', request => {
    if (request.url().includes('/mini-app/api/browser-auth/config')) activeSessionConfigRequests += 1
  })
  const activeReturnTo = '/mini-app/?intent=topup&package_id=mini&provider=lava_card'
  const activeInitData = new URLSearchParams({
    query_id: 'browser_e2e',
    user: JSON.stringify({ id: 123 }),
    auth_date: String(Math.floor(Date.now() / 1000)),
    hash: 'browser_mock',
  }).toString()
  const activeFragment = new URLSearchParams({ tgWebAppData: activeInitData }).toString()
  await activeSession.goto(
    origin + '/login?return_to=' + encodeURIComponent(activeReturnTo) + '#' + activeFragment,
    { waitUntil: 'load' },
  )
  await activeSession.waitForURL(url =>
    url.pathname === '/mini-app/' &&
    url.searchParams.get('intent') === 'topup' &&
    url.searchParams.get('package_id') === 'mini' &&
    url.searchParams.get('provider') === 'lava_card',
  )
  assert.equal(activeSessionConfigRequests, 0, 'active browser session must not request a new OIDC challenge')
  await activeSession.close()
  console.log('login/active browser session -> exact payment intent: OK')

  // Real landing CTAs: a click must show /login, not jump into unauthenticated Mini App.
  for (const [width, selector] of [[1440, '.hot-enter'], [390, '.grunge-mobile-enter']]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } })
    const response = await page.goto(origin + '/', { waitUntil: 'load' })
    assert.equal(response.status(), 200)
    assert.equal(await page.locator(selector).getAttribute('href'), '/login')
    assert.equal(await page.locator(width === 1440 ? '.hot-hero-cta' : '.mobile-grunge-cta').getAttribute('href'), '/login')
    await page.locator(selector).click()
    await page.waitForURL('**/login')
    assert.ok(page.url().endsWith('/login'), `landing CTA should lead to /login at ${width}`)
    await page.close()
    console.log(`landing -> login [${width}]: OK`)
  }

  // A browser referral is not a signed Telegram WebView launch.
  const referral = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await referral.goto(origin + '/?startapp=ci_ref_123', { waitUntil: 'load' })
  assert.ok(referral.url().includes('/?startapp=ci_ref_123'), 'browser referral stays on landing')
  assert.equal(
    await referral.locator('.mobile-grunge-cta').getAttribute('href'),
    '/login?startapp=ci_ref_123',
  )
  await referral.locator('.mobile-grunge-cta').click()
  await referral.waitForURL('**/login?startapp=ci_ref_123')
  await referral.close()
  console.log('landing/browser-referral -> login with startapp: OK')

  const failed = await browser.newPage()
  await failed.route('**/mini-app/api/browser-auth/config', route => route.fulfill({ status: 503, body: 'unavailable' }))
  await failed.goto(origin + '/login')
  await failed.getByText('Быстрый вход не настроен или недоступен.', { exact: false }).waitFor()
  assert.equal(await failed.getByRole('link', { name: /Или откройте существующую студию/ }).getAttribute('href'), '/mini-app/')
  await failed.close()
  console.log('login/auth-failure fallback: OK')

  const withoutOidc = await browser.newPage()
  await withoutOidc.route('**/mini-app/api/browser-auth/config', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: true, bot_username: 'ExampleBot', oidc_client_id: '', oidc_nonce: '' }),
  }))
  await withoutOidc.route('**/telegram-widget.js?22', route => route.fulfill({
    status: 200, contentType: 'text/javascript', body: telegramWidgetMock,
  }))
  await withoutOidc.goto(origin + '/login')
  await withoutOidc.getByText('Быстрый вход не настроен или недоступен.', { exact: false }).waitFor()
  assert.equal(await withoutOidc.getByRole('link', { name: /Или откройте существующую студию/ }).getAttribute('href'), '/mini-app/')
  await withoutOidc.close()
  console.log('login/oidc-unconfigured -> legacy widget: OK')
} finally {
  if (browser) await browser.close()
  server.close()
}
