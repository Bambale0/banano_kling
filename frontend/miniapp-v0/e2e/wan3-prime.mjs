import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

// Browser contract test: every API, upload, import and provider request is mocked.
// Only this task-owned static server is reachable. No paid work or user data.
const port = Number(process.env.WAN3_E2E_PORT || 4196)
const origin = `http://127.0.0.1:${port}`, base = origin + '/mini-app/'
const root = mkdtempSync(join(tmpdir(), 'wan3-prime-browser-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a++sAAAAASUVORK5CYII=', 'base64')
const video = readFileSync(new URL('./fixtures/seedance25-source.mp4', import.meta.url))
const wan = { id: 'wan_3_prime', label: 'Wan 3.0 Video Prime', description: 'All Wan modes',
  durations: [-1, ...Array.from({ length: 29 }, (_, i) => i + 2)], ratios: ['adaptive', '16:9', '4:3', '1:1', '3:4', '9:16'],
  supports: ['text', 'imgtxt', 'first_last', 'video', 'edit', 'file', 'link'], costs: {},
  quality_costs: { '480p': 1, '720p': 2, '1080p': 3 }, wan_resolutions: ['480P', '720P', '1080P'], requires_quality_pricing: true }
const extraModels = Array.from({ length: 17 }, (_, i) => ({ ...wan, id: `other_model_${i}`, label: `Other Model ${i}`, description: 'Synthetic model', supports: ['text'], costs: { '5': 5 } }))
const bootstrap = { ok: true, telegram_id: 424242, first_name: 'Synthetic', last_name: 'Wan QA', telegram_username: 'wan_qa', photo_url: '',
  referral_code: 'TEST', profile_link: '', referral_link: '', channel_url: '', prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0,
  bot_username: 'synthetic_bot', credits: 1000, is_admin: false, telegram_chat_available: true, mini_app_url: base, actions: [], payment_packages: [],
  image_models: [{ id: 'banana_pro', label: 'Synthetic image model', ratios: ['1:1'], max_references: 8, cost: 2 }],
  video_models: [wan, ...extraModels], recent_tasks: [], saved_references: [] }
let browser
async function setup(width = 375, behavior = {}) {
  const context = await browser.newContext({ viewport: { width, height: 840 } })
  const page = await context.newPage(); page.setDefaultTimeout(12000)
  const errors = [], quotes = [], generations = [], uploads = new Map(), completedUploads = new Set(), chunks = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    window.Telegram = { WebApp: { initData: 'query_id=wan3-browser-fixture', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
  })
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url())
    if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// synthetic fixture' })
    if (url.hostname === 'owned.test') return route.fulfill({ contentType: 'image/png', body: image })
    if (url.pathname.includes('/mini-app/api/')) {
      const body = req.headers()['content-type']?.includes('application/json') ? req.postDataJSON() : {}
      let result = { ok: true }, status = 200
      if (url.pathname.endsWith('/bootstrap')) result = bootstrap
      else if (url.pathname.endsWith('/genjutsu')) result = body.action === 'recipe_list' ? { ok: true, items: [] } : { ok: true, visible: false }
      else if (url.pathname.endsWith('/feed')) result = { ok: true, feed: [] }
      else if (url.pathname.endsWith('/prompts')) result = { ok: true, prompts: [] }
      else if (url.pathname.endsWith('/wan3/upload/init')) {
        const id = body.upload_id; assert.match(id, /^[a-f0-9]{32}$/); uploads.set(id, body)
        result = { ok: true, upload_id: id, chunk_size: 7 * 1024 * 1024 }
      } else if (url.pathname.endsWith('/wan3/upload/chunk')) chunks.push(true)
      else if (url.pathname.endsWith('/wan3/upload/complete')) {
        const upload = uploads.get(body.upload_id); assert.ok(upload, 'Unknown upload session')
        completedUploads.add(body.upload_id)
        result = { ok: true, kind: upload.kind, url: `https://owned.test/${upload.filename}`, filename: upload.filename, size: upload.size }
      } else if (url.pathname.endsWith('/wan3/upload/cancel')) {
        result = { ok: true, status: completedUploads.has(body.upload_id) ? 'completed' : 'cancelled' }
      } else if (url.pathname.endsWith('/wan3/import')) result = { ok: true, kind: body.kind, url: body.url, filename: 'page' }
      else if (url.pathname.endsWith('/wan3/quote')) {
        assert.equal(generations.length, 0, 'Quote is tested before any launch')
        quotes.push(body)
        const source = (body.recipe.reference_video_urls || []).length * 2.5
        const billed = body.recipe.duration === -1 ? 30 : source + body.recipe.duration
        result = { ok: true, quote_hash: 'synthetic-quote', reserve_cost: billed * 2, billing_duration_seconds: billed,
          source_video_duration_seconds: source, tariff_missing: false, admin_free: false, auto_duration: body.recipe.duration === -1 }
      } else if (url.pathname.endsWith('/wan3/generate')) {
        generations.push(body)
        if (behavior.unknownOnce && generations.length === 1) result = { ok: true, status: 'unknown', internal_task_id: 'wan3_browser_unknown', reserve_cost: 60 }
        else result = { ok: true, status: 'queued', internal_task_id: 'wan3_browser_task', reserve_cost: 60, credits: 940 }
      } else if (/generate|repeat|remix|payment|upload|wan3/.test(url.pathname)) throw new Error(`Unexpected mutation or unimplemented route: ${url.pathname}`)
      return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(result) })
    }
    if (url.origin === origin) return route.continue()
    return route.abort()
  })
  await page.goto(base + '?tgWebAppData=query_id%3Dwan3-e2e', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: 'Видео', exact: true }).click()
  await page.getByTestId('wan3-prime-form').waitFor()
  return { page, context, errors, quotes, generations, uploads, chunks }
}
async function upload(page, label, name, kind = 'image/png', buffer = image) {
  await page.getByLabel(label, { exact: true }).setInputFiles({ name, mimeType: kind, buffer })
  await page.getByText(name, { exact: true }).waitFor()
}
const cases = [
  ['text', 'По тексту'], ['first_frame', 'Первый кадр'], ['first_last', 'Первый и последний кадры'],
  ['reference', 'По референсам'], ['edit', 'Редактирование видео'], ['file', 'Из документа'], ['link', 'Из веб-страницы'],
]
try {
  const deadline = Date.now() + 20000
  while (true) {
    if (server.exitCode !== null) throw new Error('Task-owned browser server did not start')
    try { if ((await fetch(base)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static export not ready')
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ headless: true })
  for (const [mode, label] of cases) {
    const qa = await setup(mode === 'edit' ? 320 : 375), { page } = qa
    await page.getByRole('button', { name: label, exact: true }).click()
    if (mode === 'text' || mode === 'edit') await page.getByLabel('Инструкции Wan').fill('Изменить одежду по Image1; сохранить движение Video1.'.replace(mode === 'text' ? /по Image1; сохранить движение Video1/ : /UNUSED/, 'в кадре'))
    if (mode === 'first_frame' || mode === 'first_last') await upload(page, 'Загрузить первый кадр', 'first.png')
    if (mode === 'first_last') await upload(page, 'Загрузить последний кадр', 'last.png')
    if (mode === 'edit') {
      await upload(page, 'Загрузить исходное видео (Video1)', 'source.mp4', 'video/mp4', video)
      await upload(page, 'Загрузить фото-референсы', 'person.png')
      await upload(page, 'Загрузить видео-референсы', 'style.mp4', 'video/mp4', video)
      await upload(page, 'Загрузить аудио-референсы', 'sound.mp3', 'audio/mpeg', Buffer.from('synthetic audio'))
      await page.getByLabel('Дополнительный источник').selectOption('file')
      await upload(page, 'Загрузить документ', 'brief.pdf', 'application/pdf', Buffer.from('%PDF synthetic browser fixture'))
    }
    if (mode === 'reference') await upload(page, 'Загрузить аудио-референсы', 'audio-only.mp3', 'audio/mpeg', Buffer.from('synthetic audio'))
    if (mode === 'file') {
      await upload(page, 'Загрузить документ', 'script.md', 'text/markdown', Buffer.from('# Synthetic script'))
      await upload(page, 'Загрузить фото-референсы', 'product.png')
    }
    if (mode === 'link') {
      await page.getByText('Добавить адрес страницы', { exact: true }).click()
      await page.getByLabel('Ссылка: Веб-страница').fill('https://example.com/public-brief')
      await page.getByRole('button', { name: 'Добавить', exact: true }).last().click()
      await page.getByText('page', { exact: true }).waitFor()
      await upload(page, 'Загрузить видео-референсы', 'reference.mp4', 'video/mp4', video)
    }
    await page.getByLabel('Качество Wan').selectOption('720P')
    await page.getByLabel('Формат Wan').selectOption('9:16')
    const duration = page.getByRole('slider', { name: 'Длительность Wan', exact: true })
    const autoDuration = page.getByRole('switch', { name: 'Auto: длительность Wan', exact: true })
    assert.equal(await duration.inputValue(), '5')
    assert.equal(await duration.getAttribute('min'), '2')
    assert.equal(await duration.getAttribute('max'), '30')
    assert.equal(await duration.getAttribute('step'), '1')
    await duration.press('Home')
    assert.equal(await duration.inputValue(), '2')
    for (let step = 0; step < 5; step += 1) await duration.press('ArrowRight')
    assert.equal(await duration.getAttribute('aria-valuetext'), '7 секунд')
    await page.getByText('7 сек', { exact: true }).waitFor()
    await autoDuration.check()
    assert.equal(await autoDuration.isChecked(), true)
    assert.equal(await duration.isDisabled(), true)
    await autoDuration.uncheck()
    assert.equal(await duration.isEnabled(), true)
    assert.equal(await duration.inputValue(), '7', 'Leaving Auto restores manual seconds')
    if (mode === 'edit') await autoDuration.check()
    await page.getByLabel('Seed Wan').fill('0')
    await page.getByLabel('Аудио в результате').uncheck()
    await page.getByLabel('Проверка контента').check()
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'Overflow in ' + mode)
    await page.getByRole('button', { name: 'Рассчитать стоимость', exact: true }).click()
    const start = page.getByRole('button', { name: 'Запустить Wan', exact: true })
    await start.scrollIntoViewIfNeeded()
    assert.equal(await start.evaluate(el => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)) }), true, 'Start obscured by navigation')
    if (mode === 'edit') {
      mkdirSync('.artifacts/wan3-prime', { recursive: true })
      await page.getByTestId('wan3-prime-form').screenshot({ path: '.artifacts/wan3-prime/editor-320.png' })
    }
    await start.click()
    await page.getByText('wan3_browser_task', { exact: true }).waitFor()
    assert.equal(qa.generations.length, 1)
    const sent = qa.generations[0]
    assert.equal(sent.quote_hash, 'synthetic-quote'); assert.ok(sent.idempotency_key)
    assert.equal(sent.recipe.scenario, mode); assert.equal(sent.recipe.seed, 0); assert.equal(sent.recipe.audio, false)
    assert.equal(sent.recipe.nsfw_checker, true); assert.equal(sent.recipe.resolution, '720P'); assert.equal(sent.recipe.aspect_ratio, '9:16')
    assert.equal(sent.recipe.duration, mode === 'edit' ? -1 : 7)
    assert.deepEqual(sent.recipe, qa.quotes[0].recipe)
    if (mode === 'edit') {
      assert.deepEqual(sent.recipe.reference_video_urls, ['https://owned.test/source.mp4', 'https://owned.test/style.mp4'])
      assert.deepEqual(sent.recipe.reference_file_urls, ['https://owned.test/brief.pdf'])
      assert.equal(sent.recipe.first_frame_url, null); assert.equal(sent.recipe.last_frame_url, null)
    }
    assert.deepEqual(qa.errors, [])
    await qa.context.close()
    console.log(`PASS browser Wan ${mode}: all output fields, owned uploads/import, quote then explicit launch`)
  }
  const filter = await setup(430)
  await filter.page.locator('[data-testid="wan3-prime-form"] button[aria-expanded]').click()
  const menu = filter.page.getByTestId('model-select-menu')
  await menu.getByRole('button', { name: 'Другое', exact: true }).click()
  assert.equal(await menu.getByRole('button', { name: /Other Model/ }).count(), 8)
  await menu.getByRole('button', { name: 'Дальше', exact: true }).click()
  assert.equal(await menu.getByRole('button', { name: /Other Model/ }).count(), 8)
  await menu.getByLabel('Поиск модели').fill('Other Model 16')
  assert.equal(await menu.getByRole('button', { name: /Other Model/ }).count(), 1)
  await menu.getByLabel('Поиск модели').fill('')
  await menu.getByRole('button', { name: 'Wan', exact: true }).click()
  await menu.getByRole('button', { name: /Wan 3.0 Video Prime/ }).click()
  assert.deepEqual(filter.errors, [])
  await filter.context.close()
  console.log('PASS browser model family filtering, search, pagination and selected-model return')
  const retry = await setup(375, { unknownOnce: true })
  await retry.page.getByLabel('Инструкции Wan').fill('Синтетический рассвет.')
  await retry.page.getByRole('button', { name: 'Рассчитать стоимость', exact: true }).click()
  await retry.page.getByRole('button', { name: 'Запустить Wan', exact: true }).click()
  await retry.page.getByText('wan3_browser_unknown', { exact: true }).waitFor()
  assert.equal(await retry.page.getByLabel('Инструкции Wan').isDisabled(), true)
  assert.equal(await retry.page.getByRole('slider', { name: 'Длительность Wan', exact: true }).isDisabled(), true)
  assert.equal(await retry.page.getByRole('switch', { name: 'Auto: длительность Wan', exact: true }).isDisabled(), true)
  await retry.page.getByRole('button', { name: 'Проверить запуск', exact: true }).click()
  await retry.page.getByText('wan3_browser_task', { exact: true }).waitFor()
  assert.equal(retry.generations.length, 2)
  assert.equal(retry.generations[0].idempotency_key, retry.generations[1].idempotency_key)
  assert.deepEqual(retry.errors, [])
  await retry.context.close()
  console.log('PASS browser unknown acknowledgement preserves composer and idempotency key')
} finally {
  if (browser) await browser.close()
  server.kill('SIGTERM')
  await new Promise(resolve => server.exitCode !== null ? resolve() : server.once('exit', resolve))
  rmSync(root, { recursive: true, force: true })
}
