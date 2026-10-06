import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

const port = Number(process.env.SEEDANCE_UPLOAD_E2E_PORT || 4185)
const origin = 'http://127.0.0.1:' + port
const baseUrl = origin + '/mini-app/'
const root = mkdtempSync(join(tmpdir(), 'seedance-upload-e2e-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a++sAAAAASUVORK5CYII=', 'base64')
const video = readFileSync(new URL('./fixtures/genjutsu-result.mp4', import.meta.url))
const imageModel = { id: 'banana_pro', label: 'Nano Banana Pro', ratios: ['1:1'], qualities: ['2K'], max_references: 8, cost: 2 }
const videoModels = ['seedance_2', 'seedance_2_5', 'v3_pro'].map(id => ({
  id, label: id, durations: [5, 10], ratios: ['16:9'], supports: ['text', 'imgtxt'],
  costs: { '5': 20, '10': 40 }, resolutions: ['720p'], max_image_references: 9, max_video_references: 3,
}))
const bootstrap = { ok: true, telegram_id: 424242, first_name: 'E2E', last_name: 'Admin', telegram_username: 'e2e_admin',
  photo_url: '', referral_code: 'E2EADMIN', profile_link: '', referral_link: '', channel_url: '', prompt_repeat_balance_rub: 0,
  prompt_repeat_total_rub: 0, bot_username: 'test_bot', credits: 125, is_admin: true, telegram_chat_available: true,
  mini_app_url: baseUrl, actions: [], payment_packages: [], image_models: [imageModel], video_models: videoModels,
  recent_tasks: [], saved_references: [] }
let browser
try {
  const deadline = Date.now() + 20000
  while (true) {
    try { if ((await fetch(baseUrl)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static export not available')
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ headless: true })
  for (const width of [320, 360, 390, 430]) {
    const context = await browser.newContext({ viewport: { width, height: 820 } })
    const page = await context.newPage()
    const errors = [], forbidden = [], requests = [], uploads = []
    let published
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => {
      window.Telegram = { WebApp: { initData: 'query_id=seedance-upload-e2e', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
    })
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// fixture bridge' })
      if (url.hostname === 'example.test') return route.fulfill({ contentType: url.pathname.endsWith('.mp4') ? 'video/mp4' : 'image/png', body: url.pathname.endsWith('.mp4') ? video : image })
      if (url.pathname.includes('/mini-app/api/')) {
        const body = request.headers()['content-type']?.includes('application/json') ? JSON.parse(request.postData() || '{}') : {}
        requests.push({ path: url.pathname, ...body })
        let response = { ok: true }
        if (url.pathname.endsWith('/bootstrap')) response = bootstrap
        else if (url.pathname.endsWith('/genjutsu')) response = body.action === 'recipe_list' ? { ok: true, items: [] } : { ok: true, visible: false }
        else if (url.pathname.endsWith('/feed')) response = { ok: true, feed: [], models: [] }
        else if (url.pathname.endsWith('/prompts')) response = { ok: true, prompts: published ? [published] : [] }
        else if (url.pathname.endsWith('/upload')) {
          assert.ok(uploads.length, 'Unexpected upload')
          response = { ok: true, ...uploads.shift(), reference: null }
        } else if (url.pathname.endsWith('/admin/trends/seedance/publish-upload')) {
          assert.equal(body.preview_url, 'https://example.test/cover.png')
          assert.deepEqual(body.image_urls, ['https://example.test/face.png', 'https://example.test/style.png', 'https://example.test/excluded.png'])
          assert.deepEqual(body.video_urls, ['https://example.test/motion.mp4'])
          assert.equal(body.identity_image_index, 1)
          assert.deepEqual(body.fixed_image_indices, [2])
          assert.deepEqual(body.replaceable_video_indices, [1])
          assert.deepEqual(body.fixed_video_indices, [])
          published = { id: 77, title: body.title, description: '', prompt_text: '', prompt_hidden: true, category: 'video', model: null,
            tags: ['trend', 'trend-video'], author_id: 1, status: 'approved', likes: 0, uses_count: 0, preview_url: body.preview_url, repeat_cost: 20,
            generation_settings: { kind: 'video', ratio: '16:9', automatic_hidden_references: true,
              reference_count: 2, reference_labels: ['ВАШЕ ЛИЦО', 'ВАШЕ ВИДЕО · @Video1'],
              reference_slots: [{ media_type: 'image', position: 1, label: 'ВАШЕ ЛИЦО' }, { media_type: 'video', position: 1, label: 'ВАШЕ ВИДЕО · @Video1' }] } }
          response = { ok: true, prompt: published }
        } else if (/generate|repeat|remix|trends\/run|prompts\/submit/.test(url.pathname)) {
          forbidden.push(url.pathname); response = { ok: false, error: 'Unexpected mutating request' }
        }
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) })
      }
      if (url.origin === origin) return route.continue()
      return route.abort()
    })
    await page.goto(baseUrl + '?tgWebAppData=query_id%3De2e', { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: 'Добавить', exact: true }).click()
    await page.getByRole('button', { name: 'Видео-тренд', exact: true }).click()
    const form = page.locator('section').filter({ hasText: 'Новый тренд' })
    await form.locator('label').filter({ hasText: 'Видео-нейросеть' }).locator('select').selectOption(width === 360 ? 'seedance_2_5' : 'seedance_2')
    await form.getByPlaceholder('Название тренда').fill('Private upload trend')
    await form.getByPlaceholder('Скрытый prompt, который подставится при повторе').fill('@Image1 wears @Image2 and follows @Video1')
    uploads.push({ url: 'https://example.test/cover.png', kind: 'image', filename: 'cover.png' })
    await form.getByLabel('Preview тренда', { exact: true }).setInputFiles({ name: 'cover.png', mimeType: 'image/png', buffer: image })
    await form.locator('img[alt="Preview тренда"]').waitFor()
    uploads.push(...['face', 'style', 'excluded'].map(name => ({ url: 'https://example.test/' + name + '.png', kind: 'image', filename: name + '.png' })))
    await form.getByLabel('Фото-референсы тренда', { exact: true }).setInputFiles(['face', 'style', 'excluded'].map(name => ({ name: name + '.png', mimeType: 'image/png', buffer: image })))
    await form.getByLabel('Режим @Image3', { exact: true }).selectOption('excluded')
    uploads.push({ url: 'https://example.test/motion.mp4', kind: 'video', filename: 'motion.mp4' })
    await form.getByLabel('Видео-референсы тренда', { exact: true }).setInputFiles({ name: 'motion.mp4', mimeType: 'video/mp4', buffer: video })
    await form.getByLabel('Режим @Video1', { exact: true }).selectOption('replaceable')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)
    assert.equal(overflow, false, 'Page horizontally overflows at ' + width)
    await form.getByLabel('Режим @Video1').evaluate(element => element.scrollIntoView({ block: 'center' }))
    assert.equal(await form.getByLabel('Режим @Video1').evaluate(element => {
      const rect = element.getBoundingClientRect()
      return document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2) === element
    }), true, 'Reference mode must be reachable above navigation')
    mkdirSync('.artifacts/seedance-upload', { recursive: true })
    await page.screenshot({ path: '.artifacts/seedance-upload/refs-' + width + '.png' })
    await form.getByRole('button', { name: 'Опубликовать тренд', exact: true }).click()
    await page.getByRole('button', { name: /Повторить · 20/ }).waitFor()
    assert.equal(requests.filter(r => r.path.endsWith('/publish-upload')).length, 1)
    await page.getByRole('button', { name: /Повторить · 20/ }).click()
    await page.getByText('Заполните заменяемые слоты', { exact: true }).waitFor()
    const dialog = page.getByRole('dialog')
    assert.equal(await dialog.locator('input[type=file]').count(), 2)
    assert.equal(await dialog.locator('img[src*="style.png"],video[src*="motion.mp4"]').count(), 0)
    await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click()
    assert.equal(forbidden.length, 0, forbidden.join(', '))
    assert.equal(errors.length, 0, errors.join('\n'))
    await context.close()
    console.log('Seedance upload mobile passed ' + width)
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
