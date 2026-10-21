import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

// Synthetic owner/consumer journeys. All APIs, uploads and media are intercepted.
const port = Number(process.env.VIDEO_REPEAT_SLOTS_E2E_PORT || 4188)
const origin = `http://127.0.0.1:${port}`
const baseUrl = `${origin}/mini-app/`
const root = mkdtempSync(join(tmpdir(), 'video-repeat-slots-e2e-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const media = readFileSync(new URL('./fixtures/genjutsu-result.mp4', import.meta.url))
const secret = 'SYNTHETIC_PRIVATE_VIDEO_RECIPE'
const slots = { version: 1, available: true, cost_multiplier: 1, duration_costs: { '5': 5 }, pricing_quality: '720p', images: [
  { index: 0, role: 'first_frame', binding: 'upload' },
  { index: 1, role: 'last_frame', binding: 'fixed' },
  { index: 2, role: 'reference', binding: 'upload' },
], videos: [{ index: 0, role: 'reference', binding: 'fixed' }, { index: 1, role: 'reference', binding: 'upload' }] }
const card = { id: 777, task_id: 'synthetic-video', model: 'seedance_2_5', gen_type: 'video',
  result_url: 'https://example.test/result.mp4', preview_url: 'https://example.test/result.mp4', result_urls: ['https://example.test/result.mp4'],
  prompt: secret, prompt_hidden: true, prompt_actions_allowed: false, reference_images: [], reference_videos: [], references_hidden: true,
  likes_count: 0, shares_count: 0, comments_count: 0, aspect_ratio: '16:9', duration: 5, scenario: 'video',
  author: 'Synthetic Author', author_referral_code: 'AUTHOR', is_mine: false, is_profile_visible: true, publication_scope: 'feed',
  feed_interactions_enabled: true, remixes: 0, score: 0, created_at: '2026-10-08T00:00:00Z', repeat_reference_slots: slots }
const task = { task_id: 'owner-video', type: 'video', model: 'seedance_2_5', model_label: 'Seedance 2.5', aspect_ratio: '16:9', duration: 5,
  status: 'completed', result_url: card.result_url, prompt: 'Synthetic owner video', prompt_preview: 'Synthetic owner video', cost: 5,
  created_at: card.created_at, publication_reference_images: ['https://example.test/owner-photo.jpg'], publication_reference_image_indices: [2],
  publication_reference_videos: ['https://example.test/owner-video.mp4'], publication_reference_video_indices: [5] }
const bootstrap = { ok: true, telegram_id: 424242, first_name: 'E2E', last_name: 'Owner', telegram_username: 'e2e_owner', photo_url: '',
  referral_code: 'E2EOWNER', profile_link: '', referral_link: '', channel_url: '', prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0,
  bot_username: 'test_bot', credits: 125, is_admin: false, mini_app_url: baseUrl, actions: [], payment_packages: [], image_models: [],
  video_models: [{ id: 'seedance_2_5', label: 'Seedance 2.5', description: 'Synthetic', durations: [5], ratios: ['16:9'], supports: ['text', 'imgtxt', 'video'], costs: { '5': 5 }, max_image_references: 8, max_video_references: 5 }],
  recent_tasks: [task], saved_references: [
    { id: 'first', kind: 'image', filename: 'first.jpg', url: 'https://example.test/first.jpg' },
    { id: 'third', kind: 'image', filename: 'third.jpg', url: 'https://example.test/third.jpg' },
    { id: 'clip', kind: 'video', filename: 'clip.mp4', url: 'https://example.test/clip.mp4' },
  ] }
let browser
try {
  const deadline = Date.now() + 20000
  while (true) {
    try { if ((await fetch(baseUrl)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static export unavailable')
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ headless: true })
  for (const width of [320, 390, 430]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage()
    const errors = [], publications = [], generations = [], quotes = [], sourceRequests = [], uploadKinds = [], receiptLookups = []
    let currentCard = card
    let currentTask = { ...task }
    let credits = bootstrap.credits
    let withdrawalAllowed = false
    let generationPending = false
    let pendingTask = null
    page.on('pageerror', error => errors.push(error.message))
    page.on('dialog', dialog => dialog.accept())
    await page.addInitScript(() => {
      window.Telegram = { WebApp: { initData: 'query_id=video-repeat-e2e', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
    })
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// fixture' })
      if (url.hostname === 'example.test') {
        sourceRequests.push(url.pathname)
        return route.fulfill(url.pathname.endsWith('.mp4') ? { contentType: 'video/mp4', body: media }
          : { contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="#64748b"/></svg>' })
      }
      if (url.pathname.includes('/mini-app/api/')) {
        let response = { ok: true }, status = 200
        if (url.pathname.endsWith('/bootstrap')) response = { ...bootstrap, credits, recent_tasks: [currentTask, ...(pendingTask ? [pendingTask] : [])] }
        else if (url.pathname.endsWith('/task-detail')) {
          const requestedTask = route.request().postDataJSON().task_id
          if (requestedTask === currentTask.task_id) response = { ok: true, task: currentTask }
          else if (['video_repeat_receipt_browser', 'accepted-provider-task'].includes(requestedTask)) {
            receiptLookups.push(requestedTask)
            response = { ok: true, task: { ...task, task_id: 'accepted-provider-task', status: pendingTask?.status || 'pending', prompt: '', prompt_preview: '' } }
          } else { status = 404; response = { ok: false, error: 'Task unavailable' } }
        }
        else if (url.pathname.endsWith('/generations/share') && route.request().postDataJSON().publication_scope === 'private') {
          if (!withdrawalAllowed) { status = 503; response = { ok: false, error: 'Synthetic withdrawal unavailable' } }
          else {
            currentTask = { ...currentTask, is_public_feed: false, is_profile_visible: false, publication_scope: 'private', feed_repeat_reference_selection: { images: [], videos: [] } }
            response = { ok: true, removed: true, publication_scope: 'private' }
          }
        } else if (url.pathname.endsWith('/generations/share')) {
          const data = route.request().postDataJSON()
          publications.push(data)
          currentTask = { ...currentTask, is_public_feed: true, is_profile_visible: true, publication_scope: 'feed',
            feed_references_visible: data.references_visible, feed_repeat_reference_selection: { images: data.repeat_reference_image_indices, videos: data.repeat_reference_video_indices } }
          response = { ok: true, feed_item: { ...card, id: 888, is_mine: true, task_id: task.task_id, feed_references_visible: data.references_visible } }
        } else if (url.pathname.endsWith('/feed/item')) response = { ok: true, feed_item: currentCard }
        else if (url.pathname.endsWith('/feed/profile')) response = { ok: true, feed: [currentCard], profile: { name: 'Synthetic Author', first_name: 'Synthetic', referral_code: 'AUTHOR', posts_count: 1 } }
        else if (url.pathname.endsWith('/feed') || url.pathname.endsWith('/feed/my')) response = { ok: true, feed: [currentCard], models: [{ id: 'seedance_2_5', label: 'Seedance 2.5' }] }
        else if (url.pathname.endsWith('/prompts')) response = { ok: true, prompts: [] }
        else if (url.pathname.endsWith('/genjutsu')) response = { ok: true, visible: false }
        else if (url.pathname.endsWith('/upload')) {
          const body = route.request().postData() || ''
          assert.ok(body.includes('seedance25_video_reference'), 'Typed Seedance video uses its direct upload kind')
          uploadKinds.push('seedance25_video_reference')
          response = { ok: true, url: 'https://example.test/replacement.mp4', kind: 'video', filename: 'replacement.mp4' }
        }
        else if (url.pathname.endsWith('/generate-video')) {
          const data = route.request().postDataJSON()
          if (data.pricing_quote_only === true) {
            // Hidden fixed media never leave the server; count their seconds
            // in the quote without exposing their URLs to the consumer.
            const fixed = (currentCard.repeat_reference_slots?.videos || [])
              .filter(slot => slot.binding === 'fixed').length
            const incoming = ((data.v_reference_videos || []).length + fixed) * 5
            const output = data.v_duration || 5
            const quality = currentCard.repeat_reference_slots?.pricing_quality || '720p'
            const rate = quality === '480p' ? 0.4 : 1
            const cost = Number(((incoming + output) * rate).toFixed(2))
            response = {
              ok: true, quote_only: true, quote_hash: 'verified-' + quality + '-' + (incoming + output),
              cost, source_video_seconds: incoming, output_seconds: output,
              billable_seconds: incoming + output, admin_free: false,
            }
            quotes.push({ data, response })
          } else {
            generations.push(data)
            status = 409
            response = generationPending
              ? { ok: false, code: 'video_status_pending', task_id: 'video_repeat_receipt_browser', error: 'Видео принято провайдером. Ожидаем подтверждения.' }
              : { ok: false, code: 'repeat_permission_changed',
                  error: 'Разрешения автора изменились. Откройте публикацию заново.' }
          }
        } else if (/generate|repeat|remix|start/.test(url.pathname)) throw new Error('Unexpected generation request: ' + url.pathname)
        return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(response) })
      }
      if (url.origin === origin) return route.continue()
      return route.abort()
    })
    // Author chooses private image/video inputs independently of public display.
    await page.goto(baseUrl)
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: 'Студия', exact: true }).click()
    await page.getByRole('button', { name: /Synthetic owner video/ }).click()
    await page.getByRole('button', { name: 'Опубликовать', exact: true }).click()
    const imageConsent = page.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' })
    const videoConsent = page.getByRole('checkbox', { name: 'Видео-референс 1 для повторов' })
    assert.equal(await videoConsent.getAttribute('aria-checked'), 'false')
    await imageConsent.click(); await videoConsent.click()
    const refreshed = page.waitForResponse(response => response.url().endsWith('/bootstrap'))
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await refreshed
    assert.equal(await videoConsent.getAttribute('aria-checked'), 'true')
    await page.getByRole('button', { name: 'Опубликовать', exact: true }).first().click()
    await page.getByRole('button', { name: 'Настроить публикацию', exact: true }).waitFor()
    assert.equal(publications[0].references_visible, false)
    assert.deepEqual(publications[0].repeat_reference_image_indices, [2])
    assert.deepEqual(publications[0].repeat_reference_video_indices, [5])
    await page.getByRole('button', { name: 'Настроить публикацию', exact: true }).click()
    await page.getByRole('button', { name: 'Снять выбор', exact: true }).click()
    await page.getByRole('button', { name: 'Сохранить публикацию', exact: true }).click()
    await page.getByRole('group', { name: 'Референсы для повторов' }).waitFor({ state: 'hidden' })
    assert.deepEqual(publications[1].repeat_reference_image_indices, [])
    assert.deepEqual(publications[1].repeat_reference_video_indices, [])

    // Full withdrawal uses the scoped publication route; a failure preserves grants.
    await page.getByRole('button', { name: 'Настроить публикацию', exact: true }).click()
    await imageConsent.click(); await videoConsent.click()
    await page.getByRole('button', { name: 'Сохранить публикацию', exact: true }).click()
    await page.getByRole('group', { name: 'Референсы для повторов' }).waitFor({ state: 'hidden' })
    await page.getByRole('button', { name: 'Настроить публикацию', exact: true }).click()
    await page.getByRole('button', { name: 'Убрать публикацию', exact: true }).click()
    await page.getByText('Synthetic withdrawal unavailable', { exact: true }).waitFor()
    assert.equal(await videoConsent.getAttribute('aria-checked'), 'true')
    assert.equal(currentTask.is_profile_visible, true)
    assert.deepEqual(currentTask.feed_repeat_reference_selection, { images: [2], videos: [5] })
    withdrawalAllowed = true
    await page.getByRole('button', { name: 'Убрать публикацию', exact: true }).click()
    await page.getByRole('button', { name: 'Опубликовать', exact: true }).waitFor()
    assert.equal(currentTask.is_public_feed, false)
    assert.equal(currentTask.is_profile_visible, false)
    assert.deepEqual(currentTask.feed_repeat_reference_selection, { images: [], videos: [] })
    assert.equal(await page.evaluate(() => sessionStorage.getItem('banano:pending-publication')), null)
    await page.getByRole('button', { name: 'Опубликовать', exact: true }).click()
    assert.equal(await imageConsent.getAttribute('aria-checked'), 'false')
    assert.equal(await videoConsent.getAttribute('aria-checked'), 'false')

    await page.evaluate(() => sessionStorage.clear())
    // Every consumer entry point receives the same URL-free contract.
    for (const surface of ['Лента', 'Профиль', 'deep-link']) {
      await page.goto(baseUrl + (surface === 'deep-link' ? '?startapp=remix_777' : ''))
      await page.waitForLoadState('networkidle')
      if (surface !== 'deep-link') {
        await page.getByRole('button', { name: surface, exact: true }).click()
        await page.getByRole('button', { name: surface === 'Лента' ? 'Открыть видео' : 'Открыть публикацию' }).first().click()
        await page.getByRole('button', { name: /^Повторить(?: · [0-9]+)?$/ }).click()
      }
      const group = page.getByRole('group', { name: 'Референсы повтора', exact: true })
      try { await group.waitFor({ timeout: 10000 }) } catch (error) {
        console.log('DOM', await page.locator('body').innerText())
        console.log('BROWSER_ERRORS', errors)
        throw error
      }
      assert.equal(await group.locator('input[type=file]').count(), 3)
      assert.equal(await page.getByRole('group', { name: 'Модель', exact: true }).getByRole('button').isDisabled(), true)
      for (const button of await page.getByRole('group', { name: 'Сценарий', exact: true }).getByRole('button').all()) assert.equal(await button.isDisabled(), true)
      assert.equal((await page.locator('body').innerText()).includes(secret), false)
      assert.equal(await page.locator('textarea').first().inputValue(), '')
      const launch = page.getByRole('button', { name: /Рассчитать точную стоимость|Подтвердить цену и запустить|Запустить видео/ })
      assert.equal(await launch.isDisabled(), true)
      await page.getByRole('group', { name: 'Фото 3', exact: true }).getByRole('button', { name: 'third.jpg', exact: true }).click()
      await page.getByRole('group', { name: 'Видео 2', exact: true }).getByRole('button', { name: 'clip.mp4', exact: true }).click()
      assert.equal(await launch.isDisabled(), true)
      await page.getByRole('group', { name: 'Первый кадр · Фото 1', exact: true }).getByRole('button', { name: 'first.jpg', exact: true }).click()
      assert.equal(await launch.isEnabled(), true)
      // Server quote accounts for two 5s video references plus 5s output:
      // 15 seconds at 1🍌/s, without the old presence-only ×2.
      await page.getByText(/Точная стоимость входящих видеореференсов/).waitFor()
      await launch.click()
      const costSummary = page.getByText('Стоимость', { exact: true }).locator('..').locator('..')
      await costSummary.getByText('15', { exact: true }).waitFor()
      assert.equal(await costSummary.getByText('15', { exact: true }).count(), 1)
      await page.getByText(/Видеореференсы: 10 с \+ генерация: 5 с = 15 с/).waitFor()
      await page.getByText(/15 сек\. \(вход \+ результат\).*1🍌\/с/).waitFor()
      assert.equal(await launch.isEnabled(), true)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      if (width === 390 && surface === 'deep-link') {
        mkdirSync('test-results', { recursive: true })
        await group.scrollIntoViewIfNeeded()
        await page.screenshot({ path: 'test-results/video-repeat-slots-390.png', fullPage: true })
      }
      // A real VideoTab API rejection must keep the repeat and block a stale retry.
      await launch.click()
      await page.getByRole('alert').filter({ hasText: 'Повтор недоступен' }).waitFor()
      assert.equal(await launch.isDisabled(), true)
      const sent = generations.at(-1)
      assert.equal(sent.source_feed_gen_id, 777)
      assert.equal(sent.pricing_quote_hash, quotes.at(-1).response.quote_hash)
      assert.equal(sent.prompt, '')
      assert.deepEqual(sent.reference_images, ['https://example.test/first.jpg', 'https://example.test/third.jpg'])
      assert.deepEqual(sent.v_reference_videos, ['https://example.test/clip.mp4'])
    }
    currentCard = { ...card, repeat_reference_slots: { ...slots,
      images: slots.images.map(slot => ({ ...slot, binding: 'fixed' })), videos: slots.videos.map(slot => ({ ...slot, binding: 'fixed' })),
    } }

    credits = 7
    await page.goto(baseUrl + '?startapp=remix_777')
    await page.getByRole('group', { name: 'Референсы повтора', exact: true }).waitFor()
    assert.equal(await page.getByRole('group', { name: 'Референсы повтора', exact: true }).locator('input[type=file]').count(), 0)
    const fixedLaunch = page.getByRole('button', { name: /Рассчитать точную стоимость|Подтвердить цену и запустить|Запустить видео/ })
    assert.equal(await fixedLaunch.isEnabled(), true)
    await fixedLaunch.click()
    await page.getByText('Недостаточно бананов. Пополните баланс.', { exact: true }).waitFor()
    assert.equal(await fixedLaunch.isDisabled(), true)
    const fixedCost = page.getByText('Стоимость', { exact: true }).locator('..').locator('..')
    assert.equal(await fixedCost.getByText('15', { exact: true }).count(), 1)
    credits = 15
    const repriced = page.waitForResponse(response => response.url().endsWith('/bootstrap'))
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await repriced
    await page.getByText('Недостаточно бананов. Пополните баланс.', { exact: true }).waitFor({ state: 'hidden' })
    assert.equal(await fixedLaunch.isEnabled(), true)
    // Retained 480p quality is the server's authoritative per-second rate;
    // total cost also includes the newly uploaded video seconds.
    currentCard = { ...card, repeat_reference_slots: { version: 1, available: true, cost_multiplier: 1,
      duration_costs: { '5': 2 }, pricing_quality: '480p', images: [], videos: [{ index: 0, role: 'reference', binding: 'upload' }],
    } }
    credits = 4
    const beforeUpload = generations.length
    await page.goto(baseUrl + '?startapp=remix_777')
    await page.getByText('Качество исходного видео: 480p', { exact: true }).waitFor()

    await page.getByText(/Точная стоимость входящих видеореференсов/).waitFor()
    const retainedLaunch = page.getByRole('button', { name: /Рассчитать точную стоимость|Подтвердить цену и запустить|Запустить видео/ })
    assert.equal(await retainedLaunch.isDisabled(), true)
    await page.getByRole('group', { name: 'Видео 1', exact: true }).locator('input[type=file]').setInputFiles({ name: 'replacement.mp4', mimeType: 'video/mp4', buffer: media })
    await page.getByText('replacement.mp4', { exact: true }).waitFor()
    assert.equal(await retainedLaunch.isEnabled(), true)
    await retainedLaunch.click()
    const retainedCost = page.getByText('Стоимость', { exact: true }).locator('..').locator('..')
    await retainedCost.getByText('4', { exact: true }).waitFor()
    assert.equal(await retainedCost.getByText('4', { exact: true }).count(), 1)
    await page.getByText(/Видеореференсы: 5 с \+ генерация: 5 с = 10 с/).waitFor()
    await page.getByText(/10 сек\. \(вход \+ результат\).*0.4🍌\/с/).waitFor()
    assert.equal(await retainedLaunch.isEnabled(), true)
    assert.deepEqual(uploadKinds, ['seedance25_video_reference'])
    assert.equal(generations.length, beforeUpload, 'Uploading never launches a paid generation')

    currentCard = { ...card, repeat_reference_slots: { version: 1, available: false, images: [], videos: [] } }
    await page.goto(baseUrl + '?startapp=remix_777')
    await page.getByRole('alert').filter({ hasText: 'Повтор недоступен' }).waitFor()
    assert.equal(await page.getByRole('button', { name: /Рассчитать точную стоимость|Подтвердить цену и запустить|Запустить видео/ }).isDisabled(), true)
    // Accepted/pending goes through real HTTP parsing, the tab, and the form.
    currentCard = { ...card, repeat_reference_slots: { ...slots,
      images: slots.images.map(slot => ({ ...slot, binding: 'fixed' })), videos: slots.videos.map(slot => ({ ...slot, binding: 'fixed' })),
    } }
    credits = 100
    generationPending = true
    const beforePending = generations.length
    const beforeQuote = quotes.length
    await page.goto(baseUrl + '?startapp=remix_777')
    const pendingLaunch = page.getByRole('button', { name: /Рассчитать точную стоимость|Подтвердить цену и запустить|Запустить видео/ })
    await pendingLaunch.click()
    await page.getByText(/Видеореференсы: 10 с/).waitFor()
    assert.equal(quotes.length, beforeQuote + 1)
    assert.equal(generations.length, beforePending, 'Checking the tariff must not launch or debit')
    await pendingLaunch.click()
    await page.getByText('Видео принято, ожидаем подтверждения статуса', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: /Рассчитать точную стоимость|Подтвердить цену и запустить|Запустить видео/ }).isDisabled(), true)
    assert.equal(generations.length, beforePending + 1)
    await page.getByRole('button', { name: 'Проверить в истории', exact: true }).click()
    for (const surface of ['Лента', 'Профиль', 'deep-link']) {
      await page.goto(baseUrl + (surface === 'deep-link' ? '?startapp=remix_777' : ''))
      await page.waitForLoadState('networkidle')
      if (surface !== 'deep-link') {
        await page.getByRole('button', { name: surface, exact: true }).click()
        await page.getByRole('button', { name: surface === 'Лента' ? 'Открыть видео' : 'Открыть публикацию' }).first().click()
        await page.getByRole('button', { name: /^Повторить(?: · [0-9]+)?$/ }).click()
      }
      await page.getByText('Видео принято, ожидаем подтверждения статуса', { exact: true }).waitFor()
      assert.equal(await page.getByRole('button', { name: /Рассчитать точную стоимость|Подтвердить цену и запустить|Запустить видео/ }).isDisabled(), true)
      assert.equal(await page.getByRole('alert').filter({ hasText: 'Откройте публикацию заново' }).count(), 0)
      assert.equal(generations.length, beforePending + 1)
    }
    assert.ok(receiptLookups.includes('video_repeat_receipt_browser'), 'Owned receipt alias was resolved before canonical history reconciliation')
    pendingTask = { ...task, task_id: 'accepted-provider-task', status: 'completed', prompt_preview: '', prompt: '' }
    const reconciled = page.waitForResponse(response => response.url().endsWith('/bootstrap'))
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await reconciled
    await page.getByText('Видео принято, ожидаем подтверждения статуса', { exact: true }).waitFor({ state: 'hidden' })
    assert.equal(await page.getByRole('button', { name: /Рассчитать точную стоимость|Подтвердить цену и запустить|Запустить видео/ }).isEnabled(), true)
    assert.equal(generations.length, beforePending + 1)

    // Legacy posts now receive replacement-only descriptors from the server.
    // A hidden author photo must never fill an empty consumer input.
    generationPending = false
    pendingTask = null
    currentCard = { ...card, id: 778, task_id: 'legacy-replacement-source',
      repeat_reference_slots: { version: 1, available: true, cost_multiplier: 1,
        duration_costs: { '5': 5 }, pricing_quality: '720p',
        images: [{ index: 0, role: 'reference', binding: 'upload' }], videos: [] } }
    const beforeLegacy = generations.length
    await page.goto(baseUrl + '?startapp=remix_778')
    const ownPhoto = page.getByRole('group', { name: 'Фото 1', exact: true })
    await ownPhoto.waitFor()
    const legacyLaunch = page.getByRole('button', { name: /Рассчитать точную стоимость|Подтвердить цену и запустить|Запустить видео/ })
    assert.equal(await legacyLaunch.isDisabled(), true)
    assert.equal(generations.length, beforeLegacy)
    await ownPhoto.getByRole('button', { name: 'first.jpg', exact: true }).click()
    assert.equal(await legacyLaunch.isEnabled(), true)
    const legacyResponse = page.waitForResponse(response => response.url().endsWith('/generate-video'))
    await legacyLaunch.click()
    await legacyResponse
    if (generations.length === beforeLegacy) {
      const confirmation = page.getByRole('button', { name: /Подтвердить цену и запустить/ })
      await confirmation.waitFor()
      const submitted = page.waitForResponse(response => response.url().endsWith('/generate-video'))
      await confirmation.click()
      await submitted
    }
    assert.equal(generations.length, beforeLegacy + 1)
    assert.deepEqual(generations.at(-1).reference_images, ['https://example.test/first.jpg'])
    assert.equal(generations.at(-1).source_feed_gen_id, 778)
    assert.equal(generations.at(-1).prompt || '', '')

    // Hidden recipes do not prevent publishing the generated result.
    currentTask = { ...task, prompt: '', prompt_preview: '', prompt_hidden: true,
      prompt_actions_allowed: false, request_data: {},
      publication_reference_images: [], publication_reference_videos: [],
      publication_reference_image_indices: [], publication_reference_video_indices: [] }
    await page.goto(baseUrl)
    await page.getByRole('button', { name: 'Студия', exact: true }).click()
    await page.getByRole('button').filter({ hasText: 'Seedance 2.5' }).filter({ hasText: 'Готово' }).first().click()
    await page.getByText('Промпт автора скрыт. Результат можно опубликовать и повторить.').waitFor()
    await page.getByRole('button', { name: 'Опубликовать', exact: true }).click()
    assert.equal(await page.getByRole('button', { name: 'Prompt', exact: true }).isDisabled(), true)
    await page.getByRole('button', { name: 'Только профиль', exact: true }).click()
    await page.getByRole('button', { name: 'Опубликовать', exact: true }).first().click()
    await page.getByRole('button', { name: 'Настроить публикацию', exact: true }).waitFor()
    assert.equal(publications.at(-1).publication_scope, 'profile')
    assert.equal(publications.at(-1).prompt_visible, false)
    assert.deepEqual(publications.at(-1).repeat_reference_image_indices, [])
    assert.deepEqual(publications.at(-1).repeat_reference_video_indices, [])

    assert.equal(sourceRequests.some(path => path.includes('private')), false)
    assert.deepEqual(errors, [])
    console.log(`PASS ${width}px: typed owner consent/full withdrawal with failure preservation; accepted pending survives Feed/Profile/deep-link reopen and reconciles owned local alias with canonical history; Feed/Profile/deep-link slots; ordered payload; full retained/upload price and affordability; retained480p quote and Seedance replacement upload; rejected stale recipe; unavailable recipe`)
    await context.close()
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
