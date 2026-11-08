import assert from 'node:assert/strict'
import { createReadStream } from 'node:fs'
import { stat } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, resolve, sep } from 'node:path'
import { chromium } from 'playwright'

function commercialFixture(platform) {
  let catalog = { revision: 0, default_tariff_id: 'ordinary', default_partner_group_id: 'base',
    tariffs: { ordinary: { label: 'Обычный', prices: { 'photo:test': { amount: '2.5000', unit: 'job' } } } },
    partner_groups: { base: { label: 'Базовая', first_level_percent: '30.0000', second_level_percent: '7.0000', repeat_reward_rub: '5.00' } } }
  let settings = { revision: 0, tariff_id: null, partner_group_id: null, first_level_percent: null, second_level_percent: null, repeat_reward_rub: null }
  function effective() {
    const group = settings.partner_group_id || catalog.default_partner_group_id
    return { tariff_id: settings.tariff_id || catalog.default_tariff_id, partner_group_id: group,
      first_level_percent: settings.first_level_percent ?? catalog.partner_groups[group]?.first_level_percent ?? null,
      second_level_percent: settings.second_level_percent ?? catalog.partner_groups[group]?.second_level_percent ?? null,
      repeat_reward_rub: settings.repeat_reward_rub ?? catalog.partner_groups[group]?.repeat_reward_rub ?? null }
  }
  return {
    reply(path, request) {
      if (!path.includes('/commerce')) return null
      if (path.endsWith('/commerce')) {
        if (request.method() === 'PUT') {
          const body = request.postDataJSON()
          assert.equal(body.expected_revision, catalog.revision)
          catalog = { ...body.settings, revision: catalog.revision + 1 }
        }
        return { ok: true, catalog }
      }
      if (path.includes('/commerce/accounts/')) {
        if (request.method() === 'PUT') {
          const body = request.postDataJSON()
          assert.equal(body.expected_revision, settings.revision)
          settings = { ...body.settings, revision: settings.revision + 1 }
          if (settings.first_level_percent === '40') settings.first_level_percent = '40.0000'
        }
        return { ok: true, target: { account_id: platform === 'vk' ? 'vk-browser-account' : 'browser-account', settings, effective: effective() } }
      }
      if (path.endsWith('/commerce/quote')) {
        const body = request.postDataJSON()
        assert.deepEqual(Object.keys(body).sort(), ['price_key', 'quantity'])
        const price = catalog.tariffs[effective().tariff_id].prices[body.price_key]
        assert.equal(typeof price.amount, 'string')
        return { ok: true, quote: { id: 'browser-quote', scope: 'preview', platform, total: price.amount,
          terms: effective(), allowed_payment_providers: platform === 'vk' ? ['lava'] : [] } }
      }
      throw new Error('Unexpected commercial route ' + path)
    }
  }
}

async function checkCommercialPanel(page, platform) {
  await page.getByLabel('Код тарифа', { exact: true }).fill('creator')
  await page.getByLabel('Название тарифа', { exact: true }).fill('Креатор')
  await page.getByLabel('Позиция прайса', { exact: true }).fill('photo:test')
  await page.getByLabel('Стоимость в бананах', { exact: true }).fill('1.2500')
  await page.getByRole('button', { name: 'Сохранить цену', exact: true }).click()
  await page.getByText('Цена сохранена в общем каталоге.', { exact: true }).waitFor()
  try {
    await page.getByLabel('Тариф аккаунта', { exact: true }).selectOption('creator')
  } catch (error) {
    console.error('Commercial DOM diagnostic', await page.locator('section[aria-label="Тарифы и партнёрские условия"]').innerText(), await page.locator('select').evaluateAll(nodes => nodes.map(node => node.outerHTML)))
    throw error
  }
  await page.getByLabel('Индивидуальный процент первого уровня', { exact: true }).fill('40')
  await page.getByRole('button', { name: 'Сохранить условия аккаунта', exact: true }).click()
  await page.getByText('Индивидуальные условия сохранены.', { exact: true }).waitFor()
  await page.getByRole('button', { name: 'Рассчитать стоимость', exact: true }).click()
  await page.getByText('Стоимость: 1.2500 банана. Ставка: 40.0000%.' + (platform === 'vk' ? ' Для ВК предусмотрена только Lava.' : ''), { exact: true }).waitFor()
}

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
  browser = await chromium.launch({ headless: true, channel: process.env.E2E_BROWSER_CHANNEL || undefined })
  for (const width of [320, 430, 1280]) {
    for (const admin of [false, true]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      page.on('pageerror', error => console.error('Preview page error:', error.message))
      page.on('console', message => { if (message.type() === 'error') console.error('Preview console error:', message.text()) })
      page.setDefaultTimeout(15000)
      const previewRequests = []
      const apiRequests = []
      const clientErrors = []
      let policy = { enabled: false, revision: 0, vk_app_id: 123, vk_admin_ids: [], session_ttl_seconds: 3600, launch_max_age_seconds: 600 }
      const commercial = commercialFixture('telegram')
      let accountLink = null
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
          if (!admin && (
            path.endsWith('/settings') || path.endsWith('/wallet') || path.includes('/commerce')
          )) {
            await route.fulfill({ status: 403, json: { ok: false } })
            return
          }
          const commercePayload = commercial.reply(path, request)
          if (commercePayload) return route.fulfill({ json: commercePayload })
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
            payload = { ok: true, account: { id: 'browser-account' }, preview: { revision: policy.revision, vk_app_id: policy.vk_app_id, telegram_bot_username: 'test_bot', telegram_linked: true, linked_platforms: ['telegram'] } }
          } else if (path.endsWith('/links')) {
            assert.equal(request.postDataJSON().target_platform, 'vk')
            accountLink = { id: 'browser-invite', state: 'pending', revision: 0, token: 'c'.repeat(43), source_confirmed: false, target_confirmed: false, expires_at_epoch: 9999999999 }
            payload = { ok: true, link: accountLink }
          } else if (path.endsWith('/links/browser-invite/cancel')) {
            assert.equal(request.postDataJSON().expected_revision, accountLink.revision)
            accountLink = { ...accountLink, state: 'cancelled', revision: accountLink.revision + 1 }
            payload = { ok: true, link: accountLink }
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
        await page.getByText('Настройки общих аккаунтов', { exact: true }).click()
        try {
          await page.getByLabel('Публичный вход и привязка аккаунтов').check()
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
        await checkCommercialPanel(page, 'telegram')
        const accounts = page.getByRole('region', { name: 'Связанные аккаунты', exact: true })
        await accounts.getByLabel('Telegram привязан', { exact: true }).waitFor()
        const connect = accounts.getByRole('button', { name: 'Привязать ВКонтакте', exact: true })
        await connect.waitFor()
        const platformBox = await accounts.getByText('ВКонтакте', { exact: true }).boundingBox()
        const buttonBox = await connect.boundingBox()
        assert(platformBox.x + platformBox.width <= buttonBox.x, 'Platform name must not overlap the linking button')
        assert.equal(await accounts.evaluate(node => node.scrollWidth <= node.clientWidth), true, 'Card must not overflow')
        await accounts.screenshot({ path: resolve(process.env.TEMP || '/tmp', `neuromix-linked-accounts-${width}.png`) })
        assert.equal(previewRequests.filter(request => request.path.includes('/links')).length, 0, 'Opening an invitation must not mutate its state')
        await connect.click()
        await page.getByRole('button', { name: 'Создать ссылку', exact: true }).click()
        assert.equal(await page.getByLabel('Ссылка для другого аккаунта', { exact: true }).inputValue(), 'https://vk.com/app123#link_' + 'c'.repeat(43))
        assert.equal(await page.getByRole('button', { name: 'Подтверждаю связь аккаунтов', exact: true }).isDisabled(), true)
        await page.getByRole('button', { name: 'Отменить ссылку', exact: true }).click()
        await page.getByText('Ссылка отменена.', { exact: true }).waitFor()
      } else {
        const accounts = page.getByRole('region', { name: 'Связанные аккаунты', exact: true })
        await accounts.getByLabel('Telegram привязан', { exact: true }).waitFor()
        const connect = accounts.getByRole('button', { name: 'Привязать ВКонтакте', exact: true })
        await connect.waitFor()
        assert.equal(await page.getByText('Настройки общих аккаунтов', { exact: true }).count(), 0)
        assert.equal(await page.getByLabel('Публичный вход и привязка аккаунтов').count(), 0)
        assert(previewRequests.some(request => request.path.endsWith('/session')))
        assert(previewRequests.some(request => request.path.endsWith('/me')))
        assert.equal(previewRequests.some(request => request.path.endsWith('/settings')), false)
        assert.equal(previewRequests.some(request => request.path.endsWith('/wallet')), false)
        assert.equal(previewRequests.some(request => request.path.includes('/commerce')), false)
        await connect.click()
        await page.getByRole('button', { name: 'Создать ссылку', exact: true }).click()
        assert.equal(await page.getByLabel('Ссылка для другого аккаунта', { exact: true }).inputValue(), 'https://vk.com/app123#link_' + 'c'.repeat(43))
        await page.getByRole('button', { name: 'Отменить ссылку', exact: true }).click()
        await page.getByText('Ссылка отменена.', { exact: true }).waitFor()
      }
      assert.equal(await page.evaluate(() => Object.values(sessionStorage).some(value => /link_[A-Za-z0-9_-]{43}/.test(value))), false, 'Invitation credentials must stay out of browser storage')
      assert.deepEqual(clientErrors, [])
      console.log(`PASS shared-account admin=${admin} width=${width}`)
      await context.close()
    }
  }
  // Regression: a real expired launch returns 401; the card must remain findable.
  for (const metadataAllowed of [false, true]) {
    const context = await browser.newContext({ viewport: { width: 430, height: 900 } })
    const page = await context.newPage()
    const mutations = []
    await page.addInitScript(() => {
      window.Telegram = { WebApp: { initData: 'expired-signed-launch', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
    })
    await page.route('**/telegram-web-app.js', route => route.fulfill({ contentType: 'application/javascript', body: '// deterministic bridge' }))
    await page.route('**/mini-app/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      let payload = { ok: true, items: [], feed: [], prompts: [], categories: [], references: [], notifications: [] }
      if (path.endsWith('/bootstrap')) payload = { ...payload,
        telegram_id: 1001, first_name: 'Expired', credits: 10, is_admin: true, bot_username: 'test_bot',
        telegram_chat_available: true, telegram_bot_start_required: false, actions: [], payment_packages: [],
        image_models: [], video_models: [], recent_tasks: [], saved_references: [],
      }
      if (path.includes('/account-preview/')) {
        if (path.includes('/links')) mutations.push(path)
        if (path.endsWith('/settings') || (!metadataAllowed && path.endsWith('/session'))) {
          return route.fulfill({ status: 401, json: { ok: false, error: 'Expired launch credentials' } })
        }
        if (path.endsWith('/session')) payload = { ok: true, session_token: 's'.repeat(43), account: { id: 'regression-account' } }
        if (path.endsWith('/me')) payload = { ok: true, account: { id: 'regression-account' }, preview: {
          revision: 1, vk_app_id: 123, telegram_bot_username: 'test_bot', telegram_linked: true, linked_platforms: ['telegram'],
        } }
      }
      return route.fulfill({ json: payload })
    })
    await page.goto(base)
    await page.getByRole('button', { name: 'Профиль', exact: true }).click()
    const card = page.getByRole('region', { name: 'Связанные аккаунты', exact: true })
    await card.waitFor()
    await page.getByText('Настройки общих аккаунтов', { exact: true }).click()
    await page.getByRole('button', { name: 'Повторить загрузку настроек', exact: true }).waitFor()
    assert.equal(await page.getByText('Загрузка настроек…', { exact: true }).count(), 0)
    if (metadataAllowed) {
      await card.getByRole('button', { name: 'Привязать ВКонтакте', exact: true }).waitFor()
    } else {
      await card.getByRole('button', { name: 'Повторить проверку', exact: true }).waitFor()
      const reopen = page.getByRole('link', { name: 'Открыть приложение заново', exact: true })
      assert.equal(await reopen.getAttribute('href'), 'https://t.me/test_bot?startapp')
      assert.equal(await card.getByText('Не привязан', { exact: true }).count(), 0)
    }
    assert.deepEqual(mutations, [], 'An authentication error must never create or accept an invitation')
    console.log(`PASS settings-401 card retained metadataAllowed=${metadataAllowed}`)
    await context.close()
  }
  for (const admin of [false, true]) {
    const context = await browser.newContext({ viewport: { width: 430, height: 900 } })
    const page = await context.newPage()
    page.on('pageerror', error => console.error('VK common app page error:', error.message))
    page.on('console', message => { if (message.type() === 'error') console.error('VK common app console error:', message.text()) })
    page.setDefaultTimeout(15000)
    const requests = []
    const appCredentials = []
    const commercial = commercialFixture('vk')
    const token = 'a'.repeat(43)
    await page.route('**/telegram-web-app.js', route => route.fulfill({ contentType: 'application/javascript', body: '// deterministic bridge' }))
    await page.route('**/mini-app/api/**', async route => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      requests.push(path)
      if (!admin && (
        path.endsWith('/settings') || path.endsWith('/wallet') || path.includes('/commerce')
      )) {
        return route.fulfill({ status: 403, json: { ok: false } })
      }
      const commercePayload = commercial.reply(path, request)
      if (commercePayload) return route.fulfill({ json: commercePayload })
      let payload = { ok: true, items: [], feed: [], prompts: [], categories: [], references: [], notifications: [] }
      if (path.endsWith('/session')) {
        assert.equal(request.postDataJSON().platform, 'vk')
        payload = { ok: true, session_token: 's'.repeat(43), account: { id: 'vk-browser-account' } }
      } else if (path.endsWith('/me')) {
        payload = {
          ok: true,
          account: { id: 'vk-browser-account' },
          preview: {
            revision: 1,
            vk_app_id: 123,
            telegram_bot_username: 'test_bot',
            telegram_linked: admin,
            linked_platforms: admin ? ['telegram', 'vk'] : ['vk'],
          },
        }
      } else if (path.endsWith('/bootstrap')) {
        const body = request.postDataJSON()
        appCredentials.push(body.init_data)
        payload = {
          ok: true,
          items: [],
          feed: [],
          prompts: [],
          categories: [],
          references: [],
          notifications: [],
          telegram_id: 1001,
          first_name: 'VK',
          last_name: 'Admin',
          telegram_username: 'linked_admin',
          credits: 301,
          is_admin: admin,
          bot_username: 'test_bot',
          referral_code: 'VKADMIN',
          telegram_chat_available: false,
          telegram_bot_start_required: true,
          actions: [],
          payment_packages: [],
          image_models: [],
          video_models: [],
          recent_tasks: [],
          saved_references: [],
        }
      } else if (path.endsWith('/settings')) {
        payload = {
          ok: true,
          settings: {
            enabled: true,
            revision: 1,
            vk_app_id: 123,
            vk_admin_ids: [2001],
            session_ttl_seconds: 3600,
            launch_max_age_seconds: 600,
            link_ttl_seconds: 600,
          },
        }
      } else if (path.endsWith('/wallet')) {
        payload = {
          ok: true,
          scope: 'sandbox',
          balance: { available: '0.0000', reserved: '0.0000', revision: 0 },
          entries: [],
          receipt: null,
        }
      } else if (path.endsWith('/logout')) {
        payload = { ok: true }
      }
      await route.fulfill({ json: payload })
    })
    await page.goto(base + '?vk_app_id=123&vk_user_id=2001&sign=browser-fixture#link_' + token)
    if (admin) {
      await page.getByRole('button', { name: 'Профиль', exact: true }).waitFor()
      for (const tab of ['Студия', 'Тренды', 'Фото', 'Видео', 'Motion', 'Лента', 'Сервисы', 'Профиль']) {
        assert.equal(await page.getByRole('button', { name: tab, exact: true }).count(), 1)
      }
      assert.equal(requests.filter(path => path.includes('/links')).length, 0, 'Linked opening must not accept or confirm')
      assert.ok(requests.some(path => path.endsWith('/bootstrap')), 'Linked VK admin must initialize the shared app')
      assert.ok(appCredentials.length >= 1)
      assert.ok(appCredentials.every(value => value === 'vk_session:' + 's'.repeat(43)))
      assert.equal(await page.getByRole('heading', { name: 'Свяжите аккаунты ТГ и ВК' }).count(), 0)
      assert.equal(await page.getByRole('heading', { name: 'Разреши боту писать тебе' }).count(), 0)
      await page.getByRole('button', { name: 'Профиль', exact: true }).click()
      await page.getByText('Настройки общих аккаунтов', { exact: true }).click()
      try {
        await checkCommercialPanel(page, 'vk')
      } catch (error) {
        console.error('VK common app diagnostic', { requests, body: (await page.locator('body').innerText()).slice(0, 4000) })
        throw error
      }
    } else {
      await page.getByRole('heading', { name: 'Свяжите аккаунты ТГ и ВК', exact: true }).waitFor()
      assert.equal(await page.getByLabel('Код из ссылки').inputValue(), token)
      await page.getByLabel('ВКонтакте привязан', { exact: true }).waitFor()
      assert.equal(await page.getByText('Настройки общих аккаунтов', { exact: true }).count(), 0)
      assert.ok(requests.some(path => path.endsWith('/session')))
      assert.ok(requests.some(path => path.endsWith('/me')))
      assert.equal(requests.filter(path => path.includes('/links') || path.endsWith('/bootstrap')).length, 0)
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
