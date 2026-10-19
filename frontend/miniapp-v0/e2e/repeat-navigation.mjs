import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium, webkit } from 'playwright'

// All auth/API/media are synthetic and intercepted. Never submit a paid task.
const port = Number(process.env.REPEAT_NAVIGATION_E2E_PORT || 4201)
const origin = `http://127.0.0.1:${port}`
const baseUrl = `${origin}/mini-app/`
const root = mkdtempSync(join(tmpdir(), 'repeat-navigation-e2e-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const video = readFileSync(new URL('./fixtures/genjutsu-result.mp4', import.meta.url))
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP3sAAAAASUVORK5CYII=', 'base64')
const imageModel = { id: 'banana_pro', label: 'Nano Banana Pro', description: 'Synthetic image', cost: 10, ratios: ['9:16'], requires_reference: false, max_references: 4 }
const videoModel = { id: 'seedance_2_5', label: 'Seedance 2.5', description: 'Synthetic video', durations: [5], ratios: ['9:16'], supports: ['text', 'imgtxt', 'video'], costs: { '5': 10 } }
let browser
try {
  const deadline = Date.now() + 20000
  while (true) {
    try { if ((await fetch(baseUrl)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static export unavailable')
    await new Promise(done => setTimeout(done, 100))
  }
  for (const engine of [chromium, webkit]) {
    browser = await engine.launch({ headless: true })
    for (const [surface, kind, width] of [['feed', 'image', 320], ['profile', 'image', 390], ['feed', 'video', 430], ['profile', 'video', 390]]) {
      const context = await browser.newContext({ viewport: { width, height: 900 } })
      const page = await context.newPage()
      const model = kind === 'image' ? imageModel : videoModel
      const card = { id: 777, task_id: 'synthetic-source', model: model.id, gen_type: kind,
        result_url: `https://example.test/result.${kind === 'image' ? 'png' : 'mp4'}`, result_urls: [], prompt: '',
        prompt_hidden: true, references_hidden: true, reference_images: [], reference_videos: [],
        author: 'Synthetic author', author_referral_code: 'AUTHOR', is_mine: false, is_profile_visible: true,
        publication_scope: surface, feed_interactions_enabled: true, likes_count: 0, shares_count: 0,
        comments_count: 0, remixes: 0, score: 0, aspect_ratio: '9:16', duration: 5, scenario: 'video', created_at: '2026-10-19' }
      const template = { contract_version: 1, source_id: 777, version: 1, model: model.id, type: kind, presets: [], variables: [],
        slots: [{ slot_id: 'face', kind: 'image', role: 'reference', label: 'Ваше фото', hint: '', binding: 'upload', required: true }] }
      let draft = { ok: true, draft_id: 'synthetic-draft', revision: 0, status: 'draft', template, preset_id: null, user_values: {}, slots: {}, quote: null }
      const requests = [], errors = []
      page.on('pageerror', error => errors.push(error.message))
      await page.addInitScript(() => {
        window.Telegram = { WebApp: { initData: 'query_id=repeat-navigation-e2e', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
      })
      await page.route('**/*', async route => {
        const url = new URL(route.request().url())
        if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// fixture' })
        if (url.hostname === 'example.test') return route.fulfill(url.pathname.endsWith('.mp4') ? { contentType: 'video/mp4', body: video } : { contentType: 'image/png', body: png })
        if (!url.pathname.includes('/mini-app/api/')) return url.origin === origin ? route.continue() : route.abort()
        requests.push(url.pathname)
        let response = { ok: true }
        if (url.pathname.endsWith('/bootstrap')) response = { ok: true, smart_repeat_enabled: true, telegram_id: 424242, credits: 100,
          first_name: 'Synthetic', is_admin: false, bot_username: 'test_bot', mini_app_url: baseUrl, actions: [], payment_packages: [], recent_tasks: [],
          image_models: [{ ...imageModel, id: 'banana_2', label: 'Other image model' }, imageModel],
          video_models: [{ ...videoModel, id: 'seedance_2', label: 'Other video model' }, videoModel],
          saved_references: [1, 2, 3].map(id => ({ id, kind: 'image', filename: `saved-${id}.jpg`, url: `https://example.test/saved-${id}.jpg` })) }
        else if (url.pathname.endsWith('/feed/item')) response = { ok: true, feed_item: card }
        else if (url.pathname.endsWith('/feed') || url.pathname.endsWith('/feed/my') || url.pathname.endsWith('/feed/profile')) response = { ok: true, feed: [card], models: [], profile: { referral_code: 'AUTHOR', display_name: 'Synthetic author' } }
        else if (url.pathname.endsWith('/genjutsu')) response = { ok: true, visible: false }
        else if (url.pathname.endsWith('/prompts')) response = { ok: true, prompts: [] }
        else if (url.pathname.includes('/repeat/')) {
          const action = url.pathname.split('/').at(-1), body = route.request().postDataJSON()
          if (action === 'open') assert.equal(body.source_id, 777)
          else if (action === 'update') {
            assert.equal(body.slot_id, 'face')
            if (body.operation === 'ready') { assert.equal(Number(body.saved_reference_id), 2); assert.equal(body.url, undefined) }
            draft = { ...draft, revision: draft.revision + 1, quote: null, slots: { face: {
              state: body.operation === 'begin' ? 'UPLOADING' : body.operation.toUpperCase(),
              upload_token: 'lease', ...(body.operation === 'ready' ? { asset_id: 'owned-asset', url: `https://example.test/saved-${body.saved_reference_id}.jpg`, saved_reference_id: String(body.saved_reference_id), filename: `saved-${body.saved_reference_id}.jpg` } : {}),
            } } }
          } else if (action === 'quote') {
            assert.equal(draft.slots.face.state, 'READY')
            draft = { ...draft, quote: { cost: 10, quote_id: 'synthetic-quote' } }
          } else throw new Error('Unexpected repeat operation: ' + action)
          response = draft
        } else if (/generate|remix|repeat|upload/.test(url.pathname)) throw new Error('Unexpected legacy hydration/launch/upload: ' + url.pathname)
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(response) })
      })
      // Exercise the real publication preview button, not only a mocked dialog.
      await page.goto(baseUrl + '?startapp=feed_777')
      await page.waitForLoadState('networkidle')
      const repeat = page.getByRole('button', { name: /^Повторить/ })
      await repeat.waitFor()
      await repeat.click()
      const dialog = page.getByRole('region', { name: kind === 'image' ? 'Повторить фото' : 'Повторить видео', exact: true })
      await dialog.getByText('Модель исходной работы: ' + model.label, { exact: true }).waitFor()
      assert.equal(await page.getByRole('heading', { name: kind === 'image' ? 'Генерация фото' : 'Генерация видео', exact: true }).count(), 1)
      assert.equal(await page.getByText(/^Other (image|video) model$/).count(), 0)
      assert.equal(await dialog.getByText('Загружено обязательных референсов: 0 / 1', { exact: true }).count(), 1)
      await dialog.getByRole('button', { name: 'Выбрать файл: Ваше фото', exact: true }).click()
      await dialog.getByRole('button', { name: 'Взять из сохранённых', exact: true }).click()
      const calculate = dialog.getByRole('button', { name: 'Рассчитать стоимость' })
      assert.equal(await calculate.isDisabled(), true)
      await dialog.getByRole('button', { name: 'Выбрать: saved-2.jpg', exact: true }).click()
      await dialog.getByText('Загружено обязательных референсов: 1 / 1', { exact: true }).waitFor()
      assert.equal(draft.slots.face.url, 'https://example.test/saved-2.jpg')
      await calculate.click()
      await dialog.getByRole('button', { name: /Создать.*10/ }).waitFor()
      assert.equal(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1), true)
      assert.equal(requests.filter(path => path.endsWith('/repeat/open')).length, 1)
      assert.deepEqual(errors, [])
      await context.close()
      console.log(`${engine.name()} ${width}px ${surface}/${kind}: source model, direct repeat, explicit saved choice and quote passed`)
    }
    await browser.close(); browser = undefined
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
