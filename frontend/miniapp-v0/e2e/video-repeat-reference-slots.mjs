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
const slots = { version: 1, available: true, cost_multiplier: 2, duration_costs: { '5': 10 }, pricing_quality: '720p', images: [
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
    const errors = [], publications = [], generations = [], sourceRequests = [], uploadKinds = [], receiptLookups = []
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
          generations.push(route.request().postDataJSON())
          status = 409
          response = generationPending
            ? { ok: false, code: 'video_status_pending', task_id: 'video_repeat_receipt_browser', error: 'Видео принято провайдером. Ожидаем подтверждения.' }
            : { ok: false, error: 'Разрешения автора изменились. Откройте публикацию заново.' }
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
      const launch = page.getByRole('button', { name: /Запустить видео/ })
      assert.equal(await launch.isDisabled(), true)
      await page.getByRole('group', { name: 'Фото 3', exact: true }).getByRole('button', { name: 'third.jpg', exact: true }).click()
      await page.getByRole('group', { name: 'Видео 2', exact: true }).getByRole('button', { name: 'clip.mp4', exact: true }).click()
      assert.equal(await launch.isDisabled(), true)
      await page.getByRole('group', { name: 'Первый кадр · Фото 1', exact: true }).getByRole('button', { name: 'first.jpg', exact: true }).click()
      assert.equal(await launch.isEnabled(), true)
      const costSummary = page.getByText('Стоимость', { exact: true }).locator('..').locator('..')
      assert.equal(await costSummary.getByText('10', { exact: true }).count(), 1)
      assert.equal(await page.getByRole('button', { name: /5с.*2\/с/ }).count(), 1)
      assert.equal(await page.getByText('5 сек. • 16:9 • 2🍌/с', { exact: true }).count(), 1)
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
    assert.equal(await page.getByRole('button', { name: /Запустить видео/ }).isDisabled(), true)
    await page.getByText('Недостаточно бананов. Пополните баланс.', { exact: true }).waitFor()
    const fixedCost = page.getByText('Стоимость', { exact: true }).locator('..').locator('..')
    assert.equal(await fixedCost.getByText('10', { exact: true }).count(), 1)
    credits = 10
    const repriced = page.waitForResponse(response => response.url().endsWith('/bootstrap'))
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await repriced
    await page.getByText('Недостаточно бананов. Пополните баланс.', { exact: true }).waitFor({ state: 'hidden' })
    assert.equal(await page.getByRole('button', { name: /Запустить видео/ }).isEnabled(), true)
    // Retained480p final quote wins over bootstrap720p costs and includes its multiplier once.
    currentCard = { ...card, repeat_reference_slots: { version: 1, available: true, cost_multiplier: 2,
      duration_costs: { '5': 4 }, pricing_quality: '480p', images: [], videos: [{ index: 0, role: 'reference', binding: 'upload' }],
    } }
    credits = 4
    const beforeUpload = generations.length
    await page.goto(baseUrl + '?startapp=remix_777')
    await page.getByText('Качество исходного видео: 480p', { exact: true }).waitFor()
    const retainedCost = page.getByText('Стоимость', { exact: true }).locator('..').locator('..')
    assert.equal(await retainedCost.getByText('4', { exact: true }).count(), 1)
    assert.equal(await page.getByText('5 сек. • 16:9 • 0.8🍌/с', { exact: true }).count(), 1)
    assert.equal(await page.getByRole('button', { name: /Запустить видео/ }).isDisabled(), true)
    await page.getByRole('group', { name: 'Видео 1', exact: true }).locator('input[type=file]').setInputFiles({ name: 'replacement.mp4', mimeType: 'video/mp4', buffer: media })
    await page.getByText('replacement.mp4', { exact: true }).waitFor()
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(button => button.textContent.includes('Запустить видео'))?.disabled)
    assert.equal(await page.getByRole('button', { name: /Запустить видео/ }).isEnabled(), true)
    assert.deepEqual(uploadKinds, ['seedance25_video_reference'])
    assert.equal(generations.length, beforeUpload, 'Uploading never launches a paid generation')

    currentCard = { ...card, repeat_reference_slots: { version: 1, available: false, images: [], videos: [] } }
    await page.goto(baseUrl + '?startapp=remix_777')
    await page.getByRole('alert').filter({ hasText: 'Повтор недоступен' }).waitFor()
    assert.equal(await page.getByRole('button', { name: /Запустить видео/ }).isDisabled(), true)
    // Accepted/pending goes through real HTTP parsing, the tab, and the form.
    currentCard = { ...card, repeat_reference_slots: { ...slots,
      images: slots.images.map(slot => ({ ...slot, binding: 'fixed' })), videos: slots.videos.map(slot => ({ ...slot, binding: 'fixed' })),
    } }
    credits = 100
    generationPending = true
    const beforePending = generations.length
    await page.goto(baseUrl + '?startapp=remix_777')
    await page.getByRole('button', { name: /Запустить видео/ }).click()
    await page.getByText('Видео принято, ожидаем подтверждения статуса', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: /Запустить видео/ }).isDisabled(), true)
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
      assert.equal(await page.getByRole('button', { name: /Запустить видео/ }).isDisabled(), true)
      assert.equal(await page.getByRole('alert').filter({ hasText: 'Откройте публикацию заново' }).count(), 0)
      assert.equal(generations.length, beforePending + 1)
    }
    assert.ok(receiptLookups.includes('video_repeat_receipt_browser'), 'Owned receipt alias was resolved before canonical history reconciliation')
    pendingTask = { ...task, task_id: 'accepted-provider-task', status: 'completed', prompt_preview: '', prompt: '' }
    const reconciled = page.waitForResponse(response => response.url().endsWith('/bootstrap'))
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await reconciled
    await page.getByText('Видео принято, ожидаем подтверждения статуса', { exact: true }).waitFor({ state: 'hidden' })
    assert.equal(await page.getByRole('button', { name: /Запустить видео/ }).isEnabled(), true)
    assert.equal(generations.length, beforePending + 1)

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
