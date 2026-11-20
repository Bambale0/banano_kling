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
    if (path === '/mini-app/api/browser-auth/account' && req.method === 'POST') {
      const chunks = []
      for await (const chunk of req) chunks.push(chunk)
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
      posts.push(body)
      json(res, 200, { ok: true, init_data: initData, redirect: '/login' })
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

    const rel = path === '/account' || path === '/account/' ? '/account/index.html'
      : path === '/login' || path === '/login/' ? '/login/index.html'
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
    assert.equal(await page.getByText('Почта', { exact: true }).count(), 0, 'inactive sign-in previews must not be displayed')
    assert.equal(await page.getByText('Яндекс ID', { exact: true }).count(), 0, 'inactive provider must not be advertised')
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


  // Yandex is surfaced only by server configuration, never as an inert tile.
  const yandexGuest = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await yandexGuest.route('**/mini-app/api/web-auth/config', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, authenticated: false, providers: { yandex: true } }),
  }))
  const yandexRedirect = []
  await yandexGuest.route('**/mini-app/api/web-auth/start/yandex?**', route => {
    yandexRedirect.push(new URL(route.request().url()).searchParams.get('next'))
    return route.fulfill({ status: 302, headers: { Location: '/login?oauth_started=1' } })
  })
  await yandexGuest.goto(origin + '/login?startapp=yandex_ref')
  await yandexGuest.getByRole('link', { name: 'Продолжить с Яндекс ID' }).click()
  await yandexGuest.waitForURL('**/login?oauth_started=1')
  assert.deepEqual(yandexRedirect, ['/login?startapp=yandex_ref'])
  await yandexGuest.close()
  console.log('login/Yandex configured -> authorization start with referral: OK')

  // Verified browser-only identities must enter their own private account,
  // without a synthetic Telegram identity or forced Telegram linking.
  const yandexOnly = await browser.newPage({ viewport: { width: 390, height: 844 } })
  let legacyStudioAttempts = 0
  await yandexOnly.route('**/mini-app/api/web-auth/config', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, authenticated: true, studio_ready: false, providers: {
      yandex: true, google: false, email: false,
    } }),
  }))
  await yandexOnly.route('**/mini-app/api/web-auth/account', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      ok: true, account_id: '0123456789abcdef0123456789abcdef',
      studio_mode: 'web', connected: ['yandex'], telegram_linked: false,
      can_generate: false, providers: { yandex: true, google: false, email: false },
      balance: { available: '0.0000', reserved: '0.0000', revision: 0 },
    }),
  }))
  await yandexOnly.route('**/mini-app/api/web-auth/referral', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      ok: true, code: 'NW0123456789ABCDEF',
      url: origin + '/login?ref=NW0123456789ABCDEF',
      registrations: 0,
    }),
  }))
  await yandexOnly.route('**/mini-app/api/web-auth/studio', route => {
    legacyStudioAttempts += 1
    return route.fulfill({ status: 409, contentType: 'application/json',
      body: JSON.stringify({ ok: false, error: 'needs_telegram_link' }) })
  })
  await yandexOnly.goto(origin + '/login')
  await yandexOnly.waitForURL('**/mini-app/')
  await yandexOnly.getByRole('heading', { name: 'Ваш аккаунт NEUROMIX' }).waitFor()
  assert.equal(await yandexOnly.getByText('Яндекс ID').count(), 1)
  assert.equal(await yandexOnly.getByRole('link', { name: /Связать Telegram/ }).count(), 1)
  assert.equal(legacyStudioAttempts, 0, 'Yandex-only user must not be sent to legacy Telegram studio')
  assert.equal(await yandexOnly.getByText('Вход подтверждён').count(), 1)
  assert.equal(await yandexOnly.getByRole('textbox', { name: 'Веб-реферальная ссылка' })
    .inputValue(), origin + '/login?ref=NW0123456789ABCDEF')
  await yandexOnly.close()
  console.log('login/Yandex-only -> standalone authenticated web account (no Telegram): OK')

  // Telegram linking remains a deliberate opt-in action initiated by the
  // user, still verified server-side with a signed Telegram Login payload.
  const voluntaryLink = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await voluntaryLink.route('**/mini-app/api/web-auth/config', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, authenticated: true, studio_ready: false, providers: { yandex: true } }),
  }))
  await voluntaryLink.route('**/telegram-widget.js?22', route => route.fulfill({
    status: 200, contentType: 'text/javascript', body: telegramWidgetMock,
  }))
  await voluntaryLink.route('**/mini-app/api/web-auth/telegram', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, redirect: '/login?linked=telegram', init_data: initData }),
  }))
  await voluntaryLink.goto(origin + '/login?link=telegram')
  await voluntaryLink.getByText('Веб-вход подтверждён').waitFor()
  await voluntaryLink.locator('#ci-telegram-login').click()
  await voluntaryLink.waitForURL('**/mini-app/**')
  assert.ok(voluntaryLink.url().includes('#tgWebAppData='))
  await voluntaryLink.close()
  console.log('login/Yandex-only -> explicit verified Telegram linking -> legacy studio: OK')

  const yandexLinked = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await yandexLinked.route('**/mini-app/api/web-auth/config', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ ok: true, authenticated: true, studio_ready: true, providers: { yandex: true } }),
  }))
  await yandexLinked.route('**/mini-app/api/web-auth/studio', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, init_data: initData }),
  }))
  await yandexLinked.goto(origin + '/login?startapp=yandex_ref')
  await yandexLinked.waitForURL('**/mini-app/**')
  assert.equal(new URL(yandexLinked.url()).searchParams.get('startapp'), 'yandex_ref')
  assert.ok(yandexLinked.url().includes('#tgWebAppData='))
  await yandexLinked.close()
  console.log('login/Yandex-linked -> existing Telegram wallet with referral: OK')


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
    const visibleText = (await page.locator('body').innerText()).toLowerCase()
    for (const term of ['промпт', 'статусы задач', 'серверной авторизации', 'ai generation / 001', 'скоро']) {
      assert.ok(!visibleText.includes(term), 'internal copy leaked to public landing: ' + term)
    }
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
  await failed.getByText('Не получилось войти сразу.', { exact: false }).waitFor()
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
  await withoutOidc.getByText('Не получилось войти сразу.', { exact: false }).waitFor()
  assert.equal(await withoutOidc.getByRole('link', { name: /Или откройте существующую студию/ }).getAttribute('href'), '/mini-app/')
  await withoutOidc.close()
  console.log('login/oidc-unconfigured -> legacy widget: OK')

  // End-to-end browser-only commerce: no Telegram IDs, genuine user steps and
  // mocked external providers. The frontend uses the same account-native HTTP
  // contract as the backend integration tests above.
  for (const width of [390, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 850 } })
    const requests = []
    const taskId = 'web_' + '3'.repeat(32)
    await page.route('**/mini-app/api/web-auth/**', async route => {
      const url = new URL(route.request().url())
      const path = url.pathname
      const send = body => route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(body),
      })
      if (path.endsWith('/account')) return send({
        ok: true, account_id: '0123456789abcdef0123456789abcdef', studio_mode: 'web',
        connected: ['yandex'], telegram_linked: false,
        providers: { yandex: true, google: false, email: false },
        can_generate: true, can_topup: true,
        balance: { available: '6.0000', reserved: '0.0000', revision: 1 },
      })
      if (path.endsWith('/referral')) return send({
        ok: true, registrations: 0, code: 'NW0123456789ABCDEF',
        url: origin + '/login?ref=NW0123456789ABCDEF',
      })
      if (path.endsWith('/web-payments/packages')) return send({
        ok: true, provider: 'lava', available: true,
        packages: [{ id: 'p100', name: '100 кредитов', price_rub: '100.00', credits: '110' }],
      })
      if (path.endsWith('/web-generation/models')) return send({
        ok: true, enabled: true, models: [{
          id: 'flux_pro', label: 'GPT Image 2', type: 'image',
          price: '4.0', max_references: 4, ratios: ['1:1', '16:9'],
        }],
      })
      if (path.endsWith('/web-payments/create')) {
        requests.push({ type: 'payment', data: route.request().postDataJSON() })
        return send({
          ok: true, order_id: 'web_' + '4'.repeat(32),
          status: 'pending', amount_rub: '100.00', credits: '110',
          payment_url: 'https://gate.lava.top/payment/web-test',
        })
      }
      if (path.endsWith('/web-payments/status')) return send({
        ok: true, order_id: 'web_' + '4'.repeat(32),
        status: 'credited', amount_rub: '100.00', credits: '110',
        payment_url: null,
      })
      if (path.endsWith('/web-generation/reference')) {
        requests.push({ type: 'upload' })
        return send({ ok: true, reference_id: 'wr_' + '5'.repeat(32),
          url: origin + '/uploads/web_refs/test.png', mime: 'image/png' })
      }
      if (path.endsWith('/web-generation/quote')) {
        const quotePayload = route.request().postDataJSON()
        requests.push({ type: 'quote', data: quotePayload })
        return send({
          ok: true, price: '4.0', model: quotePayload.model,
          type: 'image', reference_count: quotePayload.reference_ids.length,
        })
      }
      if (path.endsWith('/web-generation/create')) {
        requests.push({ type: 'generation', data: route.request().postDataJSON() })
        return send({ ok: true, task_id: taskId, status: 'pending' })
      }
      if (path.endsWith('/task/' + taskId)) return send({
        ok: true, task: {
          task_id: taskId, model: 'flux_pro', type: 'image',
          status: 'completed', result_url: origin + '/uploads/web_results/stored.png',
          created_at_epoch: 1800000000, updated_at_epoch: 1800000001,
        },
      })
      if (path.endsWith('/history')) return send({ ok: true, recent_tasks: [], next_cursor: null })
      return route.fulfill({ status: 404, body: 'unknown API' })
    })
    const response = await page.goto(origin + '/account/', { waitUntil: 'load' })
    assert.equal(response.status(), 200)
    await page.getByLabel('Почта для чека').waitFor()
    await page.getByLabel('Модель').waitFor({ state: 'visible' })
    assert.equal(await page.getByLabel('Модель').inputValue(), 'flux_pro')
    await page.getByLabel('Почта для чека').fill('paid-user@example.com')
    await page.getByRole('button', { name: 'Перейти к пополнению' }).click()
    await page.getByRole('link', { name: 'Открыть страницу оплаты Lava' }).waitFor()
    assert.equal(requests.filter(item => item.type === 'payment').length, 1)
    assert.equal(requests.find(item => item.type === 'payment').data.package_id, 'p100')
    assert.ok(!('telegram_id' in requests.find(item => item.type === 'payment').data))
    await page.getByRole('button', { name: 'Проверить оплату' }).click()
    await page.getByText('Баланс пополнен на 110 кредитов.').waitFor()

    await page.locator('#web-generation-reference').setInputFiles({
      name: 'input.png', mimeType: 'image/png',
      buffer: Buffer.from('89504e470d0a1a0a000000000000000000000000', 'hex'),
    })
    await page.getByText('input.png').waitFor()
    await page.getByLabel('Описание').fill('Beautiful landscape from a reference')
    await page.getByRole('button', { name: 'Создать за 4.0 кредитов' }).click()
    await page.getByText('Задача: генерируется').waitFor()
    assert.equal(requests.filter(item => item.type === 'generation').length, 1)
    const generated = requests.find(item => item.type === 'generation').data
    assert.equal(generated.model, 'flux_pro')
    assert.deepEqual(generated.reference_ids, ['wr_' + '5'.repeat(32)])
    assert.equal(generated.expected_price, '4.0')
    assert.ok(requests.some(item => item.type === 'quote'),
      'browser must receive a server-side quote before charging')
    assert.ok(!('telegram_id' in generated) && !('account_id' in generated))
    await page.getByRole('button', { name: 'Проверить статус' }).click()
    await page.getByRole('link', { name: 'Открыть готовый результат' }).waitFor()
    assert.equal(await page.getByRole('link', { name: 'Открыть готовый результат' })
      .getAttribute('href'), origin + '/uploads/web_results/stored.png')
    const layout = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth }))
    assert.ok(layout.scrollWidth <= width + 2, 'browser-paid workflow must have no horizontal overflow')
    await page.close()
    console.log('web-native checkout/reference/photo/result [' + width + ']: OK')
  }

} finally {
  if (browser) await browser.close()
  server.close()
}
