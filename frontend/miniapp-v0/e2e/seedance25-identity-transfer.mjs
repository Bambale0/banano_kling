import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

// Everything except the isolated static export is intercepted. No provider,
// billing service or real upload is contacted by this browser test.
const port = Number(process.env.SEEDANCE_IDENTITY_E2E_PORT || 4192)
const origin = 'http://127.0.0.1:' + port
const baseUrl = origin + '/mini-app/'
const root = mkdtempSync(join(tmpdir(), 'seedance-identity-e2e-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a++sAAAAASUVORK5CYII=', 'base64')
const video = readFileSync(new URL('./fixtures/seedance25-source.mp4', import.meta.url))
const shortVideo = readFileSync(new URL('./fixtures/genjutsu-result.mp4', import.meta.url))
const photoUrls = ['https://example.test/uploads/refs/image/424242/portrait-front.png', 'https://example.test/uploads/refs/image/424242/portrait-profile.png']
const sourceUrl = 'https://example.test/uploads/refs/video/424242/source.mp4'
const model = {
  id: 'seedance_2_5', label: 'Seedance 2.5', durations: [-1, 5, 15], ratios: ['adaptive', '16:9'],
  supports: ['text', 'imgtxt', 'video'], costs: { '5': 20, '15': 60 }, quality_costs: { '480p': 3, '720p': 4 },
}
const bootstrap = {
  ok: true, telegram_id: 424242, first_name: 'E2E', last_name: 'Identity', telegram_username: 'e2e_identity',
  photo_url: '', referral_code: 'E2E', profile_link: '', referral_link: '', channel_url: '', prompt_repeat_balance_rub: 0,
  prompt_repeat_total_rub: 0, bot_username: 'test_bot', credits: 1000, is_admin: false, telegram_chat_available: true,
  mini_app_url: baseUrl, actions: [], payment_packages: [],
  image_models: [{ id: 'banana_pro', label: 'Nano Banana Pro', ratios: ['1:1'], qualities: ['2K'], max_references: 8, cost: 2 }],
  video_models: [model], recent_tasks: [], saved_references: [],
}
let browser
async function setup(width, isAdmin = false, credits = 1000) {
  const context = await browser.newContext({ viewport: { width, height: 820 } })
  const page = await context.newPage()
  page.setDefaultTimeout(30000)
  page.setDefaultNavigationTimeout(30000)
  const errors = [], generation = [], quotes = [], uploads = [], detailRequests = []
  const behavior = { quoteCost: null, rejectNext: false, feedItem: null, detailError: false, detailGate: null }
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    window.Telegram = { WebApp: { initData: 'query_id=identity-e2e', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
  })
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url())
    if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// fixture' })
    if (url.hostname === 'example.test') return route.fulfill({ contentType: url.pathname.endsWith('.mp4') ? 'video/mp4' : 'image/png', body: url.pathname.endsWith('.mp4') ? video : image })
    if (url.pathname.includes('/mini-app/api/')) {
      const body = req.headers()['content-type']?.includes('application/json') ? JSON.parse(req.postData() || '{}') : {}
      let response = { ok: true }, status = 200
      if (url.pathname.endsWith('/bootstrap')) response = { ...bootstrap, is_admin: isAdmin, credits }
      else if (url.pathname.endsWith('/genjutsu')) response = body.action === 'recipe_list' ? { ok: true, items: [] } : { ok: true, visible: false }
      else if (url.pathname.endsWith('/feed/item')) response = { ok: true, feed_item: behavior.feedItem }
      else if (url.pathname.endsWith('/feed')) response = { ok: true, feed: behavior.feedItem ? [behavior.feedItem] : [], models: [{ id: 'seedance_2_5', label: 'Seedance 2.5' }] }
      else if (url.pathname.endsWith('/task-detail')) {
        detailRequests.push(body)
        if (behavior.detailGate) await behavior.detailGate
        if (behavior.detailError) { status = 404; response = { ok: false, error: 'Identity detail unavailable' } }
        else response = { ok: true, task: { id: 'identity-source', task_id: 'identity-source', type: 'video', model: 'seedance_2_5', prompt: 'Hidden original instruction must stay hidden',
          request_data: { seedance25_identity_transfer: true, resolution: '720p', reference_images: photoUrls, v_reference_videos: [sourceUrl] } } }
      }
      else if (url.pathname.endsWith('/prompts')) response = { ok: true, prompts: [] }
      else if (url.pathname.endsWith('/upload')) {
        assert.ok(uploads.length, 'Unexpected upload')
        response = { ok: true, ...uploads.shift(), reference: null }
      } else if (url.pathname.endsWith('/generate-video')) {
        if (body.seedance25_quote_only) {
          quotes.push(body)
          assert.equal(body.seedance25_identity_transfer, true)
          assert.equal(body.seedance25_video_editing, false)
          assert.equal(body.v_duration, -1)
          assert.equal(body.v_ratio, 'adaptive')
          assert.deepEqual(body.seedance25_reference_audio_urls, [])
          assert.equal(body.seedance25_first_frame_url, null)
          if (body.v_reference_videos[0] !== sourceUrl) {
            status = 400
            response = { ok: false, error: 'Загрузите исходное видео в приложение для проверки длительности и стоимости' }
          } else {
            const cost = behavior.quoteCost ?? (body.seedance25_resolution === '720p' ? 88 : 66)
            response = { ok: true, quote_only: true, cost, billing_duration: 11, source_video_duration_seconds: 10.04,
              seedance25_identity_quote: { cost, billing_duration: 11, source_video_url: sourceUrl, resolution: body.seedance25_resolution, ...(body.source_feed_gen_id ? { source_feed_gen_id: body.source_feed_gen_id, parent_generation_id: body.source_feed_gen_id } : {}) } }
          }
        } else {
          generation.push(body)
          if (behavior.rejectNext) {
            behavior.rejectNext = false
            return route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'Стоимость изменилась. Обновите расчёт' }) })
          }
          response = { ok: true, status: 'queued', task_id: 'identity-mocked-' + generation.length, credits,
            cost: body.seedance25_identity_transfer ? 88 : 120, model_label: 'Seedance 2.5', admin_free: isAdmin,
            resolution: '720p', duration: body.v_duration, aspect_ratio: body.v_ratio, scenario: body.seedance25_scenario }
        }
      } else if (/generate|repeat|remix|payment|trends\/run|prompts\/submit/.test(url.pathname)) {
        throw new Error('Unexpected mutating request: ' + url.pathname)
      }
      return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(response) })
    }
    if (url.origin === origin) return route.continue()
    return route.abort()
  })
  await page.goto(baseUrl + '?tgWebAppData=query_id%3De2e', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: 'Видео', exact: true }).click()
  await page.getByLabel('Длительность видео', { exact: true }).waitFor()
  return { context, page, errors, generation, quotes, uploads, behavior, detailRequests }
}
async function addUploads(page, uploads) {
  uploads.push(...photoUrls.map((url, i) => ({ url, kind: 'image', filename: i ? 'portrait-profile.png' : 'portrait-front.png' })))
  await page.getByLabel('＋ Добавить фото', { exact: true }).setInputFiles(photoUrls.map((_, i) => ({ name: i ? 'portrait-profile.png' : 'portrait-front.png', mimeType: 'image/png', buffer: image })))
  await page.getByText('portrait-profile.png', { exact: true }).waitFor()
  uploads.push({ url: sourceUrl, kind: 'video', filename: 'source.mp4' })
  await page.getByLabel('＋ Добавить видео', { exact: true }).setInputFiles({ name: 'source.mp4', mimeType: 'video/mp4', buffer: video })
  await page.getByText('source.mp4', { exact: true }).waitFor()
}
try {
  const deadline = Date.now() + 20000
  while (true) {
    try { if ((await fetch(baseUrl)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static export not available')
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ headless: true })
  for (const width of [320, 375, 390, 430]) {
    const { context, page, errors, generation, quotes, uploads } = await setup(width)
    assert.equal(await page.getByRole('button', { name: /По референсам Использовать/ }).getAttribute('aria-pressed'), 'true')
    assert.equal(await page.getByLabel('Редактировать видео', { exact: true }).count(), 0)
    const slider = page.getByLabel('Длительность видео', { exact: true })
    await slider.focus(); await slider.press('Home')
    for (let n = 4; n < 15; n++) await slider.press('ArrowRight')
    await page.getByRole('button', { name: '16:9', exact: true }).click()
    await page.getByText('Для продвинутых: добавить URL или Asset ID', { exact: true }).click()
    await page.getByLabel(/Аудио — по одному URL/).fill('asset://preserved-audio')
    await addUploads(page, uploads)
    await page.getByRole('button', { name: /Замена персонажа/ }).click()
    await page.getByText(/к оплате 11с/).waitFor()
    assert.equal(await slider.isDisabled(), true)
    assert.equal(await page.getByRole('button', { name: '16:9', exact: true }).isDisabled(), true)
    assert.equal(await page.getByLabel(/Аудио — по одному URL/).count(), 0)
    await page.getByText('@Image1 · внешность', { exact: true }).waitFor()
    await page.getByText('@Image2 · внешность', { exact: true }).waitFor()
    await page.getByText('@Video1 · движения и сцена', { exact: true }).last().waitFor()
    await page.getByLabel('Промпт для Seedance 2.5', { exact: true }).fill('Сохранить одежду с фото')
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'Horizontal overflow at ' + width)
    mkdirSync('.artifacts/seedance-identity', { recursive: true })
    await page.getByText('Фото человека + исходное видео', { exact: true }).scrollIntoViewIfNeeded()
    await page.locator('section').filter({ has: page.getByText('Фото человека + исходное видео', { exact: true }) }).screenshot({ path: '.artifacts/seedance-identity/inputs-' + width + '.png' })
    const create = page.getByRole('button', { name: '🚀 Создать видео · 88🍌', exact: true })
    await create.scrollIntoViewIfNeeded()
    assert.equal(await create.evaluate(el => {
      const r = el.getBoundingClientRect()
      return el.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2))
    }), true, 'Create button blocked by navigation at ' + width)
    await page.screenshot({ path: '.artifacts/seedance-identity/price-' + width + '.png' })
    await page.getByRole('button', { name: /По референсам Использовать/ }).click()
    assert.equal(await slider.inputValue(), '15')
    assert.equal(await slider.isEnabled(), true)
    assert.equal(await page.getByRole('button', { name: '16:9', exact: true }).getAttribute('aria-pressed'), 'true')
    await page.getByText('portrait-front.png', { exact: true }).waitFor()
    await page.getByText('source.mp4', { exact: true }).waitFor()
    const advanced = page.getByText('Для продвинутых: добавить URL или Asset ID', { exact: true })
    if (!await advanced.evaluate(el => el.closest('details').open)) await advanced.click()
    assert.equal(await page.getByLabel(/Аудио — по одному URL/).inputValue(), 'asset://preserved-audio')
    await page.getByRole('button', { name: /Замена персонажа/ }).click()
    await create.waitFor()
    const identityResponse = page.waitForResponse(r => r.url().endsWith('/generate-video') && !r.request().postDataJSON()?.seedance25_quote_only)
    await create.click()
    assert.equal((await identityResponse).status(), 200)
    const identity = generation[0]
    assert.equal(identity.seedance25_identity_transfer, true)
    assert.equal(identity.seedance25_video_editing, false)
    assert.equal(identity.seedance25_scenario, 'multimodal')
    assert.equal(identity.v_duration, -1)
    assert.equal(identity.v_ratio, 'adaptive')
    assert.equal(identity.prompt, 'Сохранить одежду с фото')
    assert.deepEqual(identity.reference_images, photoUrls)
    assert.deepEqual(identity.v_reference_videos, [sourceUrl])
    assert.deepEqual(identity.seedance25_reference_audio_urls, [])
    assert.equal(identity.seedance25_first_frame_url, null)
    assert.equal(identity.seedance25_last_frame_url, null)
    assert.deepEqual(identity.seedance25_identity_quote, { cost: 88, billing_duration: 11, source_video_url: sourceUrl, resolution: '720p' })
    assert.ok(quotes.length > 0)
    // The existing shell refresh remounts forms after queueing. Open a fresh
    // ordinary-reference request to verify its independent fixed-duration path.
    await page.goto(baseUrl + '?tgWebAppData=query_id%3De2e', { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: 'Видео', exact: true }).click()
    await slider.focus(); await slider.press('Home')
    for (let n = 4; n < 15; n++) await slider.press('ArrowRight')
    await page.getByRole('button', { name: '16:9', exact: true }).click()
    await page.getByText('Для продвинутых: добавить URL или Asset ID', { exact: true }).click()
    await page.getByLabel(/Фото — по одному URL/).fill(photoUrls.join('\n'))
    await page.getByLabel(/Видео — по одному URL/).fill(sourceUrl)
    await page.getByLabel(/Аудио — по одному URL/).fill('asset://preserved-audio')
    const ordinaryResponse = page.waitForResponse(r => r.url().endsWith('/generate-video') && !r.request().postDataJSON()?.seedance25_quote_only)
    await page.getByRole('button', { name: '🚀 Создать видео · 120🍌', exact: true }).click()
    assert.equal((await ordinaryResponse).status(), 200)
    const ordinary = generation[1]
    assert.equal(ordinary.seedance25_identity_transfer, false)
    assert.equal(ordinary.seedance25_video_editing, false)
    assert.equal(ordinary.v_duration, 15)
    assert.equal(ordinary.v_ratio, '16:9')
    assert.deepEqual(ordinary.reference_images, photoUrls)
    assert.deepEqual(ordinary.seedance25_reference_audio_urls, ['asset://preserved-audio'])
    assert.equal(ordinary.seedance25_identity_quote, undefined)
    assert.deepEqual(errors, [])
    await context.close()
    console.log('Seedance identity paid and ordinary-reference regression passed ' + width)
  }

  const { context, page, errors, generation, uploads } = await setup(390)
  await page.getByRole('button', { name: /Замена персонажа/ }).click()
  await page.getByText('Добавьте 1–3 фото одного человека', { exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Добавьте фото и исходное видео', exact: true }).isDisabled(), true)
  await page.getByText('Для продвинутых: добавить URL или Asset ID', { exact: true }).click()
  const photos = page.getByLabel(/Фото — по одному URL/)
  const sources = page.getByLabel(/Видео — по одному URL/)
  await photos.fill('https://example.test/person.png')
  await page.getByText('Добавьте ровно одно исходное видео', { exact: true }).waitFor()
  await sources.fill('https://example.test/a.mp4\nhttps://example.test/b.mp4')
  await page.getByText('Добавьте ровно одно исходное видео', { exact: true }).waitFor()
  await photos.fill(['a', 'b', 'c', 'd'].map(n => 'https://example.test/' + n + '.png').join('\n'))
  await page.getByText(/оставьте не больше 3 фото/).waitFor()
  await page.getByRole('button', { name: /По референсам Использовать/ }).click()
  assert.equal((await photos.inputValue()).split('\n').length, 4, 'Excess photos must not be silently dropped')
  await page.getByRole('button', { name: /Замена персонажа/ }).click()
  await photos.fill('https://example.test/person.png')
  await sources.fill('https://external.example/source.mp4')
  await page.getByText('Загрузите исходное видео в приложение для проверки длительности и стоимости', { exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Не удалось рассчитать стоимость', exact: true }).isDisabled(), true)
  await sources.fill('')
  await page.getByLabel('＋ Загрузить исходное видео', { exact: true }).setInputFiles({ name: 'short.mp4', mimeType: 'video/mp4', buffer: shortVideo })
  await page.getByText('Исходное видео должно длиться 4–30 секунд', { exact: true }).waitFor()
  assert.equal(uploads.length, 0)
  assert.deepEqual(generation, [])
  assert.deepEqual(errors, [])
  await context.close()
  console.log('Seedance identity missing/excess refs, mode preservation, unknown and short source validation passed')

  const poor = await setup(375, false, 20)
  await addUploads(poor.page, poor.uploads)
  await poor.page.getByRole('button', { name: /Замена персонажа/ }).click()
  await poor.page.getByText(/к оплате 11с/).waitFor()
  assert.equal(await poor.page.getByRole('button', { name: 'Не хватает 68🍌', exact: true }).isDisabled(), true)
  await poor.page.getByRole('button', { name: /480p/ }).click()
  await poor.page.getByRole('button', { name: 'Не хватает 46🍌', exact: true }).waitFor()
  assert.deepEqual(poor.generation, [])
  assert.deepEqual(poor.errors, [])
  await poor.context.close()
  console.log('Seedance identity server-priced insufficient balance and resolution requote passed')

  const stale = await setup(390)
  await addUploads(stale.page, stale.uploads)
  await stale.page.getByRole('button', { name: /Замена персонажа/ }).click()
  await stale.page.getByRole('button', { name: '🚀 Создать видео · 88🍌', exact: true }).waitFor()
  stale.behavior.rejectNext = true
  stale.behavior.quoteCost = 96
  await stale.page.getByRole('button', { name: '🚀 Создать видео · 88🍌', exact: true }).click()
  await stale.page.getByText('Стоимость изменилась. Обновите расчёт', { exact: true }).waitFor()
  await stale.page.getByRole('button', { name: '🚀 Создать видео · 96🍌', exact: true }).waitFor()
  assert.equal(stale.generation.length, 1, 'Requote must never auto-launch')
  const retryResponse = stale.page.waitForResponse(r => r.url().endsWith('/generate-video') && !r.request().postDataJSON()?.seedance25_quote_only)
  await stale.page.getByRole('button', { name: '🚀 Создать видео · 96🍌', exact: true }).click()
  assert.equal((await retryResponse).status(), 200)
  assert.equal(stale.generation[1].seedance25_identity_quote.cost, 96)
  assert.deepEqual(stale.errors, [])
  await stale.context.close()
  console.log('Seedance identity rejected quote refresh requires another explicit launch passed')

  const ownItem = { id: 77, task_id: 'identity-source', model: 'seedance_2_5', gen_type: 'video',
    result_url: 'https://example.test/result.mp4', result_urls: ['https://example.test/result.mp4'],
    preview_url: photoUrls[0], prompt: null, likes_count: 0, shares_count: 0, comments_count: 0,
    aspect_ratio: '9:16', duration: -1, scenario: 'video', reference_images: [], reference_videos: [],
    references_hidden: true, author: 'E2E', is_mine: true, remixes: 0, score: 0,
    created_at: '2026-10-06T00:00:00Z', prompt_hidden: true, prompt_actions_allowed: false, feed_references_visible: false }
  for (const mode of ['own', 'denied', 'foreign', 'close', 'navigate', 'deeplink']) {
    const repeat = await setup(390)
    repeat.behavior.feedItem = { ...ownItem, is_mine: mode !== 'foreign' }
    repeat.behavior.detailError = mode === 'denied'
    let release
    if (mode === 'close' || mode === 'navigate') repeat.behavior.detailGate = new Promise(resolve => { release = resolve })
    if (mode === 'deeplink' || mode === 'navigate') {
      await repeat.page.goto(baseUrl + '?tgWebAppData=query_id%3De2e&startapp=remix_77', { waitUntil: 'domcontentloaded' })
    } else {
      await repeat.page.getByRole('button', { name: 'Лента', exact: true }).click()
      await repeat.page.getByRole('button', { name: 'Открыть видео', exact: true }).click()
      await repeat.page.getByRole('button', { name: 'Повторить', exact: true }).click()
    }
    if (mode === 'own' || mode === 'deeplink') {
      await repeat.page.getByRole('button', { name: '🚀 Создать видео · 88🍌', exact: true }).waitFor()
      assert.equal(await repeat.page.getByLabel('Промпт для Seedance 2.5', { exact: true }).inputValue(), '')
      assert.equal((await repeat.page.locator('body').innerText()).includes('Hidden original instruction'), false)
      assert.equal(repeat.detailRequests.length, 1)
      assert.equal(repeat.quotes.at(-1).source_feed_gen_id, 77)
      assert.deepEqual(repeat.quotes.at(-1).reference_images, photoUrls)
      const response = repeat.page.waitForResponse(r => r.url().endsWith('/generate-video') && !r.request().postDataJSON()?.seedance25_quote_only)
      await repeat.page.getByRole('button', { name: '🚀 Создать видео · 88🍌', exact: true }).click()
      assert.equal((await response).status(), 200)
      assert.equal(repeat.generation[0].source_feed_gen_id, 77)
      assert.equal(repeat.generation[0].seedance25_identity_quote.source_feed_gen_id, 77)
      assert.equal(repeat.generation[0].seedance25_identity_transfer, true)
    } else if (mode === 'denied') {
      await repeat.page.getByText('Identity detail unavailable', { exact: true }).waitFor()
      assert.equal(repeat.quotes.length, 0)
      assert.equal(repeat.generation.length, 0)
    } else if (mode === 'foreign') {
      await repeat.page.getByText('Генерация видео', { exact: true }).waitFor()
      assert.equal(repeat.detailRequests.length, 0)
      assert.equal(repeat.quotes.length, 0)
      assert.equal(await repeat.page.getByLabel('Промпт для Seedance 2.5', { exact: true }).count(), 0)
    } else {
      const detailDeadline = Date.now() + 5000
      while (!repeat.detailRequests.length && Date.now() < detailDeadline) await new Promise(resolve => setTimeout(resolve, 10))
      assert.equal(repeat.detailRequests.length, 1, 'Owner detail request must start')
      if (mode === 'close') await repeat.page.getByRole('button', { name: 'Закрыть', exact: true }).click()
      else await repeat.page.getByRole('button', { name: 'Фото', exact: true }).click()
      const detailResponse = repeat.page.waitForResponse(r => r.url().endsWith('/task-detail'))
      release()
      await detailResponse
      await repeat.page.waitForTimeout(400)
      assert.equal(await repeat.page.getByLabel('Промпт для Seedance 2.5', { exact: true }).count(), 0)
      assert.equal(repeat.quotes.length, 0)
      assert.equal(repeat.generation.length, 0)
    }
    assert.deepEqual(repeat.errors, [])
    await repeat.context.close()
    console.log('Seedance identity repeat ' + mode + ' passed')
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
