import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

// Synthetic owner/consumer journeys. All APIs, uploads and media are intercepted.
const port = Number(process.env.SMART_REPEAT_E2E_PORT || 4199)
const origin = `http://127.0.0.1:${port}`
const baseUrl = `${origin}/mini-app/`
const root = mkdtempSync(join(tmpdir(), 'smart-repeat-e2e-'))
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
const bootstrap = { ok: true, smart_repeat_enabled: true, telegram_id: 424242, first_name: 'E2E', last_name: 'Owner', telegram_username: 'e2e_owner', photo_url: '',
  referral_code: 'E2EOWNER', profile_link: '', referral_link: '', channel_url: '', prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0,
  bot_username: 'test_bot', credits: 125, is_admin: false, mini_app_url: baseUrl, actions: [], payment_packages: [], image_models: [],
  video_models: [{ id: 'seedance_2_5', label: 'Seedance 2.5', description: 'Synthetic', durations: [5], ratios: ['16:9'], supports: ['text', 'imgtxt', 'video'], costs: { '5': 5 }, max_image_references: 8, max_video_references: 5 }],
  recent_tasks: [task], saved_references: [
    { id: 'first', kind: 'image', filename: 'first.jpg', url: 'https://example.test/first.jpg' },
    { id: 'third', kind: 'image', filename: 'third.jpg', url: 'https://example.test/third.jpg' },
    { id: 'clip', kind: 'video', filename: 'clip.mp4', url: 'https://example.test/clip.mp4' },
  ] }
const template = { contract_version: 1, source_id: 777, version: 1, model: 'seedance_2_5', type: 'video', presets: [], variables: [], slots: [
  { slot_id: 'face', kind: 'image', role: 'reference', label: 'Ваше лицо', hint: 'Фото лица', binding: 'upload', required: true },
  { slot_id: 'car', kind: 'image', role: 'reference', label: 'Ваша машина', hint: 'Фото машины', binding: 'upload', required: true },
] }
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP3sAAAAASUVORK5CYII=', 'base64')
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
    const errors = [], launches = [], bindings = []
    let draft = { ok: true, draft_id: 'synthetic-draft', revision: 0, status: 'draft', template, preset_id: null, user_values: {}, slots: {}, quote: null }
    let credits = 125
    let releaseUpload = () => {}
    let holdUpload = true
    let dropReply = width === 390
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => {
      window.Telegram = { WebApp: { initData: 'query_id=smart-repeat-e2e', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
    })
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// fixture' })
      if (url.hostname === 'example.test') return route.fulfill(url.pathname.endsWith('.mp4') ? { contentType: 'video/mp4', body: media } : { contentType: 'image/png', body: png })
      if (!url.pathname.includes('/mini-app/api/')) return route.continue()
      let response = { ok: true }
      if (url.pathname.endsWith('/bootstrap')) response = { ...bootstrap, credits, recent_tasks: draft.task_id ? [{ ...task, task_id: draft.task_id, status: 'pending', prompt: '', prompt_preview: '', prompt_hidden: true }] : [], saved_references: [] }
      else if (url.pathname.endsWith('/feed/item')) response = { ok: true, feed_item: card }
      else if (url.pathname.endsWith('/feed') || url.pathname.endsWith('/feed/my')) response = { ok: true, feed: [card] }
      else if (url.pathname.endsWith('/genjutsu')) response = { ok: true, visible: false }
      else if (url.pathname.endsWith('/prompts')) response = { ok: true, prompts: [] }
      else if (url.pathname.endsWith('/upload')) {
        const raw = route.request().postData() || ''
        const name = raw.match(/filename="([^"]+)"/)?.[1] || 'file.png'
        if (holdUpload) await new Promise(resolve => { releaseUpload = resolve })
        response = { ok: true, kind: 'image', url: `https://example.test/owned/${name}`, filename: name }
      } else if (url.pathname.includes('/repeat/')) {
        const action = url.pathname.split('/').at(-1)
        const body = route.request().postDataJSON()
        if (action === 'update') {
          draft = { ...draft, revision: draft.revision + 1, quote: null, slots: { ...draft.slots } }
          if (body.operation === 'remove') delete draft.slots[body.slot_id]
          else {
            const previous = draft.slots[body.slot_id] || {}
            draft.slots[body.slot_id] = { ...previous, state: body.operation === 'begin' ? 'UPLOADING' : body.operation.toUpperCase(),
              upload_token: body.operation === 'begin' ? body.slot_id + '-' + draft.revision : previous.upload_token }
            if (body.operation === 'ready') {
              assert.equal(body.upload_token, previous.upload_token)
              draft.slots[body.slot_id] = { ...draft.slots[body.slot_id], url: body.url, asset_id: body.slot_id + '-asset' }
              bindings.push([body.slot_id, body.url])
            }
          }
        } else if (action === 'quote') {
          assert.ok(template.slots.every(slot => draft.slots[slot.slot_id]?.state === 'READY'))
          draft = { ...draft, quote: { cost: 10, quote_id: 'server-quote' } }
        } else if (action === 'launch') {
          assert.equal(body.quote_id, 'server-quote')
          assert.equal(draft.status, 'draft')
          launches.push(body); credits -= 10
          draft = { ...draft, status: 'launched', task_id: 'accepted-smart-repeat' }
          if (dropReply) { dropReply = false; return route.abort('failed') }
          response = { ok: true, task_id: draft.task_id, status: 'queued', credits }
        }
        if (action !== 'launch') response = draft
      } else if (/generate|remix|start/.test(url.pathname)) throw new Error('Legacy launch bypass: ' + url.pathname)
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(response) })
    })
    await page.goto(baseUrl + '?startapp=remix_777')
    const dialog = page.getByRole('dialog').filter({ has: page.getByRole('heading', { name: 'Повторить видео' }) })
    await dialog.waitFor()
    const calculate = dialog.getByRole('button', { name: 'Рассчитать стоимость' })
    assert.equal(await calculate.isDisabled(), true)
    await dialog.getByLabel('Загрузить: Ваша машина').setInputFiles({ name: 'car.png', mimeType: 'image/png', buffer: png })
    await page.waitForTimeout(150)
    assert.equal(await calculate.isDisabled(), true)
    assert.equal(launches.length, 0)
    holdUpload = false; releaseUpload()
    await dialog.getByText('Загружено обязательных референсов: 1 / 2', { exact: true }).waitFor()
    await dialog.getByLabel('Загрузить: Ваше лицо').setInputFiles({ name: 'face.png', mimeType: 'image/png', buffer: png })
    await dialog.getByText('Загружено обязательных референсов: 2 / 2', { exact: true }).waitFor()
    assert.deepEqual(bindings.slice(0, 2), [['car', 'https://example.test/owned/car.png'], ['face', 'https://example.test/owned/face.png']])
    await page.reload()
    await dialog.getByText('Загружено обязательных референсов: 2 / 2', { exact: true }).waitFor()
    await dialog.getByRole('button', { name: 'Удалить файл', exact: true }).first().click()
    await dialog.getByText('Загружено обязательных референсов: 1 / 2', { exact: true }).waitFor()
    assert.equal(await calculate.isDisabled(), true)
    await dialog.getByLabel('Загрузить: Ваше лицо').setInputFiles({ name: 'face2.png', mimeType: 'image/png', buffer: png })
    await dialog.getByText('Загружено обязательных референсов: 2 / 2', { exact: true }).waitFor()
    await calculate.click()
    const launch = dialog.getByRole('button', { name: /Создать.*10/ })
    await launch.evaluate(button => { button.click(); button.click() })
    await dialog.getByText('Задача сохранена в истории.', { exact: true }).waitFor()
    assert.equal(launches.length, 1); assert.equal(credits, 115)
    assert.equal(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1), true)
    assert.ok(!(await page.locator('body').innerText()).includes(secret))
    assert.deepEqual(errors, [])
    await context.close()
    console.log(`Smart repeat ${width}px: reverse uploads, pending guard, reload/remove, one launch${width === 390 ? ', lost response recovery' : ''} passed`)
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
