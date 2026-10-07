import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright'

// Standalone CI regression against the mounted production export. Telegram,
// every API, and remote media are mocked; no real bot or generation is used.
const port = Number(process.env.BOT_START_E2E_PORT || 4177)
const origin = `http://127.0.0.1:${port}`
const baseUrl = `${origin}/mini-app/`
const referenceUrl = 'https://example.test/bot-start-reference.svg'
const draft = 'Keep my selected photo tab, unsent prompt, and reference after Start.'
const bootstrap = {
  ok: true, telegram_id: 424242, first_name: 'E2E', last_name: 'Start',
  telegram_username: 'e2e_start', photo_url: '', referral_code: 'E2ESTART',
  profile_link: '', referral_link: '', channel_url: '', prompt_repeat_balance_rub: 0,
  prompt_repeat_total_rub: 0, bot_username: 'test_bot', credits: 125, is_admin: false,
  mini_app_url: baseUrl, actions: [], payment_packages: [],
  image_models: [{ id: 'banana_pro', label: 'Nano Banana Pro', description: 'Test image model',
    cost: 1, ratios: ['1:1', '9:16'], requires_reference: false, max_references: 8,
    qualities: ['1K', '2K'], quality_costs: { '1K': 1, '2K': 2 } }],
  video_models: [{ id: 'v3_pro', label: 'Kling 3 Pro', description: 'Test video model',
    durations: [5], ratios: ['16:9'], supports: ['text'], costs: { '5': 2 } }],
  recent_tasks: [],
  saved_references: [{ id: 1, filename: 'bot-start-reference.svg', kind: 'image',
    url: referenceUrl, created_at: '2026-10-06T00:00:00Z', source: 'upload' }],
}
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1',
  '--directory', '.e2e-server'], { stdio: 'ignore' })
let browser

async function waitForServer() {
  const deadline = Date.now() + 20_000
  while (Date.now() < deadline) {
    if (server.exitCode !== null) throw new Error(`Static server exited: ${server.exitCode}`)
    try { if ((await fetch(baseUrl)).ok) return } catch {}
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error('Bot Start static export server did not start')
}

async function emitReturn(page, event, visible = true) {
  await page.evaluate(({ event, visible }) => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: visible ? 'visible' : 'hidden' })
    if (event === 'activated') {
      for (const handler of window.__telegramHandlers.activated || []) handler()
    } else if (event === 'visibilitychange') document.dispatchEvent(new Event(event))
    else window.dispatchEvent(new Event(event))
  }, { event, visible })
}

try {
  await waitForServer()
  browser = await chromium.launch({ headless: true })
  for (const width of [320, 375, 390, 430]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' })
    const page = await context.newPage()
    page.setDefaultTimeout(10_000)
    const errors = []
    const unexpected = []
    const bootstrapRequests = []
    const generatedRequests = []
    const generatedTasks = new Map()
    const pending = []
    let chatAvailable = true
    let startRequirement = 'auto'
    const startRequired = () => startRequirement === 'auto' ? !chatAvailable : startRequirement
    let responseMode = 'ok'
    page.on('pageerror', error => errors.push(error.message))

    await page.addInitScript(() => {
      window.__openedBotLinks = []
      window.__nativeWriteAccessCalls = 0
      window.__telegramHandlers = {}
      // Mark the abortable capability request at the fetch boundary, so the
      // app's normal five-second polling cannot consume a hung-check fixture.
      const originalFetch = window.fetch.bind(window)
      window.fetch = (input, init) => {
        if (String(input).endsWith('/bootstrap') && init?.signal) {
          const headers = new Headers(init.headers)
          headers.set('x-e2e-capability-check', '1')
          return originalFetch(input, { ...init, headers })
        }
        return originalFetch(input, init)
      }
      window.Telegram = { WebApp: {
        initData: 'query_id=bot-start-e2e', initDataUnsafe: {},
        ready() {}, expand() {},
        requestWriteAccess() { window.__nativeWriteAccessCalls += 1 /* Deliberately never calls back. */ },
        openTelegramLink(url) { window.__openedBotLinks.push(url) },
        onEvent(event, handler) {
          const handlers = window.__telegramHandlers[event] || []
          if (!handlers.includes(handler)) handlers.push(handler)
          window.__telegramHandlers[event] = handlers
        },
        offEvent(event, handler) {
          window.__telegramHandlers[event] = (window.__telegramHandlers[event] || []).filter(value => value !== handler)
        },
      } }
      // Never allow a browser fallback to open an external Telegram page.
      window.open = url => { window.__openedBotLinks.push(url); return null }
    })

    await page.route('**/*', async route => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname.endsWith('/telegram-web-app.js')) {
        await route.fulfill({ status: 200, contentType: 'application/javascript', body: '// deterministic Telegram bridge' })
        return
      }
      if (url.href === referenceUrl) {
        await route.fulfill({ status: 200, contentType: 'image/svg+xml',
          body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#b99132"/></svg>' })
        return
      }
      if (url.pathname.includes('/mini-app/api/')) {
        const endpoint = url.pathname.split('/').at(-1)
        const json = body => ({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
        if (endpoint === 'bootstrap') {
          bootstrapRequests.push(JSON.parse(request.postData() || '{}'))
          if (responseMode === 'hang' && request.headers()['x-e2e-capability-check'] === '1') {
            pending.push(async available => {
              // An aborted request may already be closed; a late response must
              // never alter the UI even if the transport still accepts it.
              await route.fulfill(json({ ...bootstrap, telegram_chat_available: available, telegram_bot_start_required: !available })).catch(() => {})
            })
            return
          }
          if (responseMode === 'error') {
            await route.fulfill({ ...json({ ok: false, error: 'Synthetic bootstrap failure' }), status: 503 })
            return
          }
          await route.fulfill(json({ ...bootstrap, recent_tasks: [...generatedTasks.values()], telegram_chat_available: chatAvailable,
            ...(startRequired() === 'missing' ? {} : { telegram_bot_start_required: startRequired() }) }))
        } else if (endpoint === 'generate-image' || endpoint === 'generate-video') {
          const body = JSON.parse(request.postData() || '{}')
          const kind = endpoint === 'generate-image' ? 'image' : 'video'
          generatedRequests.push({ kind, body, chatAvailable, startRequired: startRequired() })
          const task = {
            task_id: 'optional-' + kind, type: kind, status: 'pending',
            model: kind === 'image' ? body.img_service : body.v_model,
            model_label: kind === 'image' ? 'Nano Banana Pro' : 'Kling 3 Pro',
            aspect_ratio: kind === 'image' ? body.img_ratio : body.v_ratio,
            prompt: body.prompt, prompt_preview: body.prompt, cost: 1,
            created_at: '2026-10-06T00:00:00Z', result_url: null,
          }
          generatedTasks.set(task.task_id, task)
          await route.fulfill(json({ ok: true, status: 'queued', task_id: task.task_id,
            credits: 125, cost: 1, model_label: task.model_label }))
        } else if (endpoint === 'task-detail') {
          const body = JSON.parse(request.postData() || '{}')
          assert.ok(generatedTasks.has(body.task_id), 'Only synthetic generated tasks may be read')
          await route.fulfill(json({ ok: true, task: generatedTasks.get(body.task_id) }))
        } else if (endpoint === 'prompts') {
          await route.fulfill(json({ ok: true, prompts: [], items: [], has_more: false }))
        } else if (endpoint === 'feed') {
          await route.fulfill(json({ ok: true, items: [], has_more: false }))
        } else if (endpoint === 'genjutsu' && JSON.parse(request.postData() || '{}').action === 'availability') {
          await route.fulfill(json({ ok: true, visible: false }))
        } else if (endpoint === 'client-log') {
          await route.fulfill(json({ ok: true }))
        } else {
          unexpected.push(request.method() + ' ' + url.href)
          await route.fulfill({ ...json({ ok: false, error: 'Unexpected offline E2E request' }), status: 500 })
        }
        return
      }
      if (url.origin === origin && request.method() === 'GET') {
        await route.continue()
        return
      }
      unexpected.push(request.method() + ' ' + url.href)
      await route.abort('blockedbyclient')
    })

    // A direct referral is retained in /start; the existing Mini App URL stays
    // unchanged so the user can return to the same selected form.
    await page.goto(baseUrl + '?startapp=ref_E2ESTART')
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: 'Фото', exact: true }).click()
    const prompt = page.getByPlaceholder('Опишите сцену, стиль, свет, камеру, детали персонажей и желаемый результат...')
    await prompt.fill(draft)
    await page.getByRole('button', { name: 'bot-start-reference.svg', exact: true }).click()
    await page.getByRole('button', { name: '9:16', exact: true }).click()
    const selectedReference = page.locator('img[src="' + referenceUrl + '"]')
    await selectedReference.waitFor()
    const promptNode = await prompt.elementHandle()
    const referenceNode = await selectedReference.elementHandle()
    const originalUrl = page.url()
    const gate = page.getByRole('dialog', { name: 'Разреши боту писать тебе' })
    const openBot = gate.getByRole('button', { name: 'Открыть бота', exact: true })
    const retry = gate.getByRole('button', { name: 'Проверить снова', exact: true })
    const status = gate.getByRole('status')

    async function assertDraftPreserved(label) {
      assert.equal(await prompt.inputValue(), draft, label + ': prompt preserved')
      assert.equal(await promptNode.evaluate(node => node.isConnected), true, label + ': form never unmounted')
      assert.equal(await referenceNode.evaluate(node => node.isConnected), true, label + ': reference never unmounted')
      assert.equal(await selectedReference.count(), 1, label + ': selected reference preserved')
      assert.equal(await page.getByRole('button', { name: 'bot-start-reference.svg', exact: true }).count(), 0,
        label + ': reference remains selected rather than returning to library')
      assert.equal(await page.getByRole('heading', { name: 'Генерация фото', exact: true }).count(), 1,
        label + ': selected photo tab preserved')
      assert.equal(page.url(), originalUrl, label + ': launch URL preserved')
    }

    chatAvailable = false
    await emitReturn(page, 'focus')
    await gate.waitFor()
    await assertDraftPreserved('gate appears')
    const controls = await gate.locator('button').evaluateAll(buttons => buttons.map(button => {
      const rect = button.getBoundingClientRect()
      return { left: rect.left, right: rect.right, height: rect.height }
    }))
    assert.ok(controls.every(rect => rect.left >= 0 && rect.right <= width + 1 && rect.height >= 44),
      'Gate controls must fit and remain tappable at ' + width + 'px')
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    mkdirSync('test-results', { recursive: true })
    await page.screenshot({ path: 'test-results/bot-start-gate-' + width + '.png' })

    const clickResult = await openBot.evaluate(button => {
      const before = window.__openedBotLinks.length
      button.click()
      return { opened: window.__openedBotLinks.slice(before), nativeCalls: window.__nativeWriteAccessCalls }
    })
    assert.deepEqual(clickResult, {
      opened: ['https://t.me/test_bot?start=ref_E2ESTART'], nativeCalls: 0,
    }, 'Primary CTA must synchronously open Start even when native permission never calls back')
    assert.equal(await gate.isVisible(), true, 'Opening Telegram does not confirm delivery access')
    assert.equal(await openBot.isEnabled(), true)

    await retry.click()
    await status.getByText(/Доступ пока не подтверждён/).waitFor()
    assert.equal(await gate.isVisible(), true, 'False server capability keeps gate')
    responseMode = 'error'
    await retry.click()
    await status.getByText(/Не удалось проверить доступ/).waitFor()
    assert.equal(await retry.isEnabled(), true, 'Network failure remains retryable')
    assert.equal(await openBot.isEnabled(), true, 'Network failure never hides primary CTA')

    // A slow check can be abandoned immediately by opening the bot again.
    responseMode = 'hang'
    await retry.click()
    await gate.getByRole('button', { name: 'Проверяем…', exact: true }).waitFor()
    assert.equal(await openBot.isEnabled(), true)
    await openBot.click()
    await retry.waitFor()
    assert.equal(pending.length, 1, 'Explicit check is in flight')
    await pending.shift()(true)
    await page.waitForTimeout(100)
    assert.equal(await gate.isVisible(), true, 'Cancelled late success cannot dismiss gate')

    const timeoutStarted = Date.now()
    await retry.click()
    await gate.getByRole('button', { name: 'Проверяем…', exact: true }).waitFor()
    await status.getByText(/Не удалось проверить доступ/).waitFor({ timeout: 15_000 })
    assert.ok(Date.now() - timeoutStarted < 15_000, 'Hung check must end within the 12s timeout plus test tolerance')
    assert.equal(await retry.isEnabled(), true)
    assert.equal(await openBot.isEnabled(), true)
    assert.equal(await gate.isVisible(), true)
    assert.equal(pending.length, 1, 'Only the abortable capability check is delayed')
    await pending.shift()(true)
    responseMode = 'ok'
    await retry.click()
    await status.getByText(/Доступ пока не подтверждён/).waitFor()
    assert.equal(await gate.isVisible(), true, 'Late timed-out success cannot unlock a later false check')
    await assertDraftPreserved('timeout and retry')

    for (const event of ['focus', 'visibilitychange', 'activated']) {
      const checked = page.waitForResponse(response => response.url().endsWith('/bootstrap'))
      await emitReturn(page, event)
      await checked
      await status.getByText(/Доступ пока не подтверждён/).waitFor()
      assert.equal(await gate.isVisible(), true, event + ': false capability must keep gate')
    }

    // Hidden WebViews do not run a return check. Observe one turn only; the
    // app's unrelated five-second polling is intentionally left unmodified.
    const beforeHidden = bootstrapRequests.length
    await emitReturn(page, 'visibilitychange', false)
    await page.waitForTimeout(100)
    assert.equal(bootstrapRequests.length, beforeHidden, 'Hidden visibility event does not refresh')
    await emitReturn(page, 'visibilitychange', true)
    await status.getByText(/Доступ пока не подтверждён/).waitFor()

    // Transport availability is not the offer criterion. The server must
    // explicitly clear the known-never-started flag before this offer closes.
    chatAvailable = true
    startRequirement = true
    const stillRequired = page.waitForResponse(response => response.url().endsWith('/bootstrap'))
    await retry.click()
    const stillRequiredPayload = await (await stillRequired).json()
    assert.equal(stillRequiredPayload.telegram_chat_available, true)
    assert.equal(stillRequiredPayload.telegram_bot_start_required, true)
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    assert.equal(await gate.isVisible(), true, 'Availability alone cannot clear an explicit Start requirement')
    startRequirement = 'auto'

    // Each return closes the offer when the server explicitly clears the flag.
    for (const event of ['activated', 'focus', 'visibilitychange']) {
      chatAvailable = true
      const checked = page.waitForResponse(response => response.url().endsWith('/bootstrap'))
      await emitReturn(page, event)
      const confirmed = await (await checked).json()
      assert.equal(confirmed.telegram_bot_start_required, false, event + ': server clears Start requirement')
      await gate.waitFor({ state: 'hidden' })
      await assertDraftPreserved(event + ' successful return')
      if (event !== 'visibilitychange') {
        chatAvailable = false
        await emitReturn(page, 'focus')
        await gate.waitFor()
        await openBot.click()
      }
    }


    // A fresh document has never opened Start. Delivery remains unconfirmed,
    // but declining the offer must allow the normal image and video flows.
    assert.equal(generatedRequests.length, 0, 'Start flow itself never generates')
    chatAvailable = false
    await page.reload()
    await gate.waitFor()
    await gate.getByRole('button', { name: 'Пропустить', exact: true }).click()
    await gate.waitFor({ state: 'hidden' })
    const deliveryBanner = page.getByRole('complementary', { name: 'Доставка результатов' })
    const receiveInBot = deliveryBanner.getByRole('button', { name: 'Получать в боте', exact: true })
    await receiveInBot.waitFor()
    assert.deepEqual(await page.evaluate(() => window.__openedBotLinks), [], 'Skip never opens Start')
    await page.getByRole('button', { name: 'Фото', exact: true }).click()
    await prompt.fill(draft)
    await page.getByRole('button', { name: 'bot-start-reference.svg', exact: true }).click()
    const skippedPromptNode = await prompt.elementHandle()
    const skippedReferenceNode = await selectedReference.elementHandle()
    await receiveInBot.click()
    await gate.waitFor()
    responseMode = 'hang'
    await retry.click()
    await gate.getByRole('button', { name: 'Проверяем…', exact: true }).waitFor()
    await gate.getByRole('button', { name: 'Пропустить', exact: true }).click()
    await receiveInBot.waitFor()
    assert.equal(pending.length, 1)
    await pending.shift()(true)
    responseMode = 'ok'
    await page.waitForTimeout(100)
    assert.equal(await deliveryBanner.isVisible(), true,
      'Skip cancels pending check; late true cannot mark delivery as granted')

    for (const event of ['focus', 'visibilitychange', 'activated']) {
      const refreshed = event === 'activated' ? null
        : page.waitForResponse(response => response.url().endsWith('/bootstrap'))
      await emitReturn(page, event)
      if (refreshed) {
        const response = await (await refreshed).json()
        assert.equal(response.telegram_chat_available, false, 'Server delivery capability remains false')
        assert.equal(response.telegram_bot_start_required, true, 'Skip does not change known-never-started status')
      }
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      assert.equal(await gate.count(), 0, event + ': skipped offer must not reappear')
      assert.equal(await deliveryBanner.isVisible(), true, event + ': delivery remains optional and unconfirmed')
      assert.equal(await prompt.inputValue(), draft, event + ': skipping preserves draft')
      assert.equal(await skippedPromptNode.evaluate(node => node.isConnected), true, event + ': form remains mounted')
      assert.equal(await skippedReferenceNode.evaluate(node => node.isConnected), true, event + ': reference remains mounted')
    }

    await page.getByRole('button', { name: 'Запустить фото', exact: true }).click()
    const details = page.getByRole('heading', { name: 'Детали задачи', exact: true })
    await details.waitFor()
    assert.equal(generatedRequests.length, 1, 'Image creation is allowed without Start')
    assert.equal(generatedRequests[0].kind, 'image')
    assert.equal(generatedRequests[0].body.prompt, draft)
    assert.deepEqual(generatedRequests[0].body.reference_images, [referenceUrl])
    assert.equal(generatedRequests[0].chatAvailable, false, 'Image creation does not grant delivery')
    assert.equal(generatedRequests[0].startRequired, true, 'Image creation does not mark bot started')
    await details.locator('..').getByRole('button').click()
    await details.waitFor({ state: 'hidden' })

    await page.getByRole('button', { name: 'Видео', exact: true }).click()
    const videoPrompt = page.getByPlaceholder('Опишите движение камеры, сцену, свет, ритм, физику движения и желаемый cinematic-эффект...')
    await videoPrompt.fill('Offline optional-delivery video draft')
    assert.equal(await gate.count(), 0, 'Tab changes must not re-open a skipped offer')
    await page.getByRole('button', { name: 'Запустить видео', exact: true }).click()
    await details.waitFor()
    assert.equal(generatedRequests.length, 2, 'Video creation is allowed without Start')
    assert.equal(generatedRequests[1].kind, 'video')
    assert.equal(generatedRequests[1].body.prompt, 'Offline optional-delivery video draft')
    assert.equal(generatedRequests[1].chatAvailable, false, 'Video creation does not grant delivery')
    assert.equal(generatedRequests[1].startRequired, true, 'Video creation does not mark bot started')
    await details.locator('..').getByRole('button').click()
    await details.waitFor({ state: 'hidden' })
    assert.deepEqual(await page.evaluate(() => window.__openedBotLinks), [], 'Both generations run without opening Start')
    assert.equal(await page.evaluate(() => window.__nativeWriteAccessCalls), 0)

    // Explicit refresh can remount the application; dismissal lasts through
    // that refresh and a full reload of the same Mini App session.
    const headerRefreshed = page.waitForResponse(response => response.url().endsWith('/bootstrap'))
    await page.locator('header').getByRole('button').first().click()
    await headerRefreshed
    await receiveInBot.waitFor()
    assert.equal(await gate.count(), 0, 'Header refresh preserves skipped offer')
    await page.reload()
    await receiveInBot.waitFor()
    assert.equal(await gate.count(), 0, 'Page reload preserves session dismissal')
    await receiveInBot.click()
    await gate.waitFor()
    assert.equal(await openBot.isEnabled(), true, 'Start remains accessible after Skip and reload')
    await retry.click()
    await status.getByText(/Доступ пока не подтверждён/).waitFor()
    assert.equal(await gate.isVisible(), true, 'Skip never turns delivery capability true')
    await gate.getByRole('button', { name: 'Пропустить', exact: true }).click()
    await receiveInBot.waitFor()
    await deliveryBanner.scrollIntoViewIfNeeded()
    const bannerBounds = await deliveryBanner.boundingBox()
    assert.ok(bannerBounds && bannerBounds.x >= 0 && bannerBounds.x + bannerBounds.width <= width + 1,
      'Optional delivery banner fits ' + width + 'px')
    await page.screenshot({ path: 'test-results/bot-start-skipped-' + width + '.png' })

    // Existing/blocked/unknown accounts must never be inferred to be new
    // merely because delivery is unavailable. Clear dismissal to prove the
    // missing offer is driven by the server flag, rather than saved Skip.
    for (const requirement of [false, 'missing']) {
      chatAvailable = false
      startRequirement = requirement
      await page.evaluate(() => window.sessionStorage.clear())
      await page.reload()
      await page.getByRole('button', { name: 'Фото', exact: true }).click()
      await prompt.fill('Existing account stays usable during a delivery outage')
      await page.waitForLoadState('networkidle')
      assert.equal(await gate.count(), 0, String(requirement) + ': unavailable delivery must not trigger Start offer')
      assert.equal(await deliveryBanner.count(), 0, String(requirement) + ': no optional banner without explicit requirement')
      responseMode = 'error'
      const failedRefresh = page.waitForResponse(response =>
        response.url().endsWith('/bootstrap') && response.status() === 503)
      await emitReturn(page, 'focus')
      await failedRefresh
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      assert.equal(await gate.count(), 0, String(requirement) + ': refresh failure cannot create an offer')
      assert.equal(await deliveryBanner.count(), 0)
      assert.equal(await prompt.inputValue(), 'Existing account stays usable during a delivery outage')
      responseMode = 'ok'
      const recoveredRefresh = page.waitForResponse(response =>
        response.url().endsWith('/bootstrap') && response.status() === 200)
      await emitReturn(page, 'focus')
      const payload = await (await recoveredRefresh).json()
      assert.equal(payload.telegram_chat_available, false)
      assert.equal(payload.telegram_bot_start_required, requirement === false ? false : undefined)
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      assert.equal(await gate.count(), 0, String(requirement) + ': no offer after successful delivery-false refresh')
      assert.equal(await deliveryBanner.count(), 0)
      assert.deepEqual(await page.evaluate(() => window.__openedBotLinks), [])
    }

    assert.equal(await page.evaluate(() => window.__nativeWriteAccessCalls), 0)
    assert.ok(bootstrapRequests.every(payload => payload.start_param_fallback === 'ref_E2ESTART'),
      'Capability checks must preserve referral attribution')
    assert.deepEqual(unexpected, [], 'All API and media calls are explicitly mocked; no native confirm endpoint')
    assert.deepEqual(errors, [], 'No browser page errors at ' + width + 'px')
    if (process.env.BOT_START_QA_SCREENSHOTS) {
      mkdirSync(process.env.BOT_START_QA_SCREENSHOTS, { recursive: true })
      await page.screenshot({ path: process.env.BOT_START_QA_SCREENSHOTS + '/bot-start-return-' + width + '.png', fullPage: true })
    }
    console.log('PASS ' + width + 'px: synchronous Start, no native prompt, false/error/cancel/12s timeout, focus/visibility/activated returns, tab/draft/reference retained, optional Skip survives refresh/reload, image/video creation without Start, explicit new-user flag only, no legacy/error-induced offer, offline transport')
    await context.close()
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
