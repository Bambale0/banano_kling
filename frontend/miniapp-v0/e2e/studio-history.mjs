import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

// Public assets may be tested, but every API/media/provider call is intercepted.
const remote = process.env.STUDIO_HISTORY_E2E_ORIGIN
const port = Number(process.env.STUDIO_HISTORY_E2E_PORT || 4199)
const origin = remote || `http://127.0.0.1:${port}`, base = origin + '/mini-app/'
const root = mkdtempSync(join(tmpdir(), 'studio-history-e2e-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = remote ? null : spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const media = readFileSync(new URL('./fixtures/genjutsu-result.mp4', import.meta.url))
const makeTask = index => ({ feed_id: index, task_id: `history-${index}`, type: 'video', model: 'seedance_2_5', model_label: 'Seedance 2.5',
  aspect_ratio: '16:9', duration: 5, status: 'completed', result_url: 'https://example.test/result.mp4',
  created_at: '2026-10-21T10:00:00Z', prompt: index === 12 ? 'Older bot publication' : `Owned video ${index}`,
  prompt_preview: index === 12 ? 'Older bot publication' : `Owned video ${index}`, cost: 5 })
const newest = Array.from({ length: 8 }, (_, i) => makeTask(20 - i))
const original = { ...makeTask(12), is_public_feed: true, is_profile_visible: true, publication_scope: 'feed',
  publication_reference_images: ['https://example.test/own-photo.jpg'], publication_reference_image_indices: [2],
  publication_reference_videos: ['https://example.test/own-video.mp4'], publication_reference_video_indices: [5],
  feed_repeat_reference_selection: { images: [], videos: [] } }
const bootstrap = { ok: true, telegram_id: 424242, first_name: 'Synthetic', last_name: 'Owner', telegram_username: 'e2e_owner', photo_url: '',
  referral_code: 'SYNTHETIC', profile_link: '', referral_link: '', channel_url: '', prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0,
  bot_username: 'synthetic_bot', credits: 125, is_admin: false, telegram_chat_available: true, actions: [], payment_packages: [],
  image_models: [], video_models: [], recent_tasks: newest, saved_references: [] }
let browser
try {
  const deadline = Date.now() + 20000
  while (true) {
    if (server && server.exitCode !== null) throw new Error('Task-owned server exited')
    try { if ((await fetch(base)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static export unavailable')
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ headless: true })
  for (const width of [320, 390, 430]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage(); page.setDefaultTimeout(12000)
    const errors = [], cursors = [], publications = []
    let current = { ...original }, failNextPage = true
    page.on('pageerror', error => errors.push(error.message))
    page.on('dialog', dialog => dialog.accept())
    await page.addInitScript(() => { window.Telegram = { WebApp: { initData: 'query_id=synthetic-history', ready() {}, expand() {}, onEvent() {}, offEvent() {} } } })
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// synthetic Telegram' })
      if (url.origin === 'https://example.test') return route.fulfill({ contentType: url.pathname.endsWith('.mp4') ? 'video/mp4' : 'image/svg+xml', body: url.pathname.endsWith('.mp4') ? media : '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240"/>' })
      if (url.pathname.includes('/mini-app/api/')) {
        let result = { ok: true }, status = 200
        const body = request.method() === 'POST' ? request.postDataJSON() : {}
        if (url.pathname.endsWith('/bootstrap')) result = bootstrap
        else if (url.pathname.endsWith('/task-history')) {
          assert.equal(body.init_data, 'query_id=synthetic-history')
          cursors.push(body.cursor)
          if (failNextPage) { failNextPage = false; status = 503; result = { ok: false, error: 'private server detail must stay hidden' } }
          else if (body.cursor === 'history-13') result = { ok: true, recent_tasks: [current, ...Array.from({ length: 7 }, (_, i) => makeTask(11 - i))], next_cursor: 'history-5' }
          else if (body.cursor === 'history-5') result = { ok: true, recent_tasks: [makeTask(4), makeTask(3), makeTask(2)], next_cursor: null }
          else throw new Error('Unexpected history cursor')
        } else if (url.pathname.endsWith('/task-detail')) {
          assert.equal(body.task_id, current.task_id)
          const { prompt_preview, ...detail } = current
          result = { ok: true, task: detail }
        } else if (url.pathname.endsWith('/generations/share')) {
          publications.push(body)
          assert.equal(body.task_id, current.task_id)
          current = { ...current, feed_repeat_reference_selection: { images: body.repeat_reference_image_indices, videos: body.repeat_reference_video_indices } }
          result = { ok: true, feed_item: { ...current, id: current.feed_id, is_mine: true } }
        } else if (url.pathname.endsWith('/genjutsu')) result = { ok: true, visible: false }
        else if (url.pathname.endsWith('/prompts')) result = { ok: true, prompts: [] }
        else if (/generate|repeat|payment|upload/.test(url.pathname)) throw new Error('Unexpected generation/payment/upload mutation')
        return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(result) })
      }
      return url.origin === origin ? route.continue() : route.abort()
    })
    await page.goto(base, { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: 'Студия', exact: true }).click()
    await page.getByRole('button', { name: 'Загрузить ещё', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: 'Не удалось загрузить историю' }).waitFor()
    assert.equal(await page.getByText('private server detail must stay hidden').count(), 0)
    await page.getByRole('button', { name: 'Загрузить ещё', exact: true }).click()
    const older = page.getByRole('button', { name: /Older bot publication/ })
    await older.click()
    await page.getByRole('button', { name: 'Настроить публикацию', exact: true }).click()
    await page.getByRole('checkbox', { name: 'Фото-референс 1 для повторов', exact: true }).click()
    await page.getByRole('checkbox', { name: 'Видео-референс 1 для повторов', exact: true }).click()
    await page.getByRole('button', { name: 'Сохранить публикацию', exact: true }).click()
    await page.waitForFunction(() => document.body.textContent.includes('Настройки публикации сохранены') || document.body.textContent.includes('Опубликовано'))
    assert.equal(publications.length, 1)
    assert.deepEqual(publications[0].repeat_reference_image_indices, [2])
    assert.deepEqual(publications[0].repeat_reference_video_indices, [5])
    await page.getByRole('heading', { name: 'Детали задачи', exact: true }).locator('..').getByRole('button').click()
    await page.getByRole('button', { name: 'Загрузить ещё', exact: true }).click()
    await page.getByText('Owned video 2', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: 'Загрузить ещё', exact: true }).count(), 0)
    assert.equal(await page.getByText('Older bot publication', { exact: true }).count(), 1)
    assert.deepEqual(cursors, ['history-13', 'history-13', 'history-5'])
    assert.deepEqual(errors, [])
    console.log(`PASS ${width}px: older bot publication beyond eight, retry, own photo/video reference settings, all history pages, no generation/payment calls`)
    await context.close()
  }
} finally {
  await browser?.close()
  if (server) { server.kill('SIGTERM'); await new Promise(resolve => server.exitCode !== null ? resolve() : server.once('exit', resolve)) }
  rmSync(root, { recursive: true, force: true })
}
