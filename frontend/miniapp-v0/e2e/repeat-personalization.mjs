import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

// Production export, synthetic authenticated DTOs only. Every API and external
// request is intercepted: no real generation, publication, billing or Telegram.
const port = Number(process.env.REPEAT_PERSONALIZATION_E2E_PORT || 4198)
const origin = 'http://127.0.0.1:' + port
const base = origin + '/mini-app/'
const root = mkdtempSync(join(tmpdir(), 'repeat-personalization-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const fields = [{ key: 'clothes', label: 'Одежда', type: 'text', required: true, max_length: 160, choices: ['red dress', 'black suit'] }]
const models = ['v3_pro', 'wan_3', 'wan_3_prime'].map(id => ({ id, label: id, description: 'Synthetic',
  durations: [5], ratios: ['16:9'], supports: ['text'], costs: { '5': 5 },
  quality_costs: { '720p': 2, '1080p': 3 }, wan_resolutions: ['720P', '1080P'] }))
let browser
try {
  const deadline = Date.now() + 20000
  while (true) {
    try { if ((await fetch(base)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static export unavailable')
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ headless: true })
  for (const admin of [true, false]) {
    for (const model of ['banana_pro', 'v3_pro', 'wan_3', 'wan_3_prime']) {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
      const page = await context.newPage()
      const errors = [], quotes = [], mutations = []
      page.on('pageerror', error => errors.push(error.message))
      await page.addInitScript(() => {
        window.Telegram = { WebApp: { initData: 'query_id=repeat-preview-fixture', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
      })
      const isImage = model === 'banana_pro'
      const card = { id: 777, model, gen_type: isImage ? 'image' : 'video', is_mine: false,
        task_id: 'synthetic', result_url: 'https://example.test/result', preview_url: 'https://example.test/result',
        result_urls: ['https://example.test/result'], prompt: '', prompt_hidden: true, prompt_actions_allowed: false,
        references_hidden: true, reference_images: [], reference_videos: [], scenario: 'text', aspect_ratio: '16:9',
        duration: 5, author: 'Synthetic', likes_count: 0, shares_count: 0, remixes: 0, score: 0,
        ...(admin ? { repeat_user_fields: fields } : {}) }
      await page.route('**/*', async route => {
        const url = new URL(route.request().url())
        if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// fixture' })
        if (url.hostname === 'example.test') return route.abort()
        if (url.pathname.includes('/mini-app/api/')) {
          let data = { ok: true }
          if (url.pathname.endsWith('/bootstrap')) data = { ok: true, telegram_id: 424242, first_name: 'Synthetic',
            is_admin: admin, credits: 100, telegram_chat_available: true, image_models: [{ id: 'banana_pro', label: 'Nano Banana Pro',
              ratios: ['1:1', '16:9'], qualities: ['2K'], max_references: 8, cost: 1 }], video_models: models,
            recent_tasks: [], saved_references: [], actions: [], payment_packages: [], mini_app_url: base }
          else if (url.pathname.endsWith('/feed/item')) data = { ok: true, feed_item: card }
          else if (url.pathname.endsWith('/feed')) data = { ok: true, feed: [card] }
          else if (url.pathname.endsWith('/prompts')) data = { ok: true, prompts: [] }
          else if (url.pathname.endsWith('/trends/catalog')) data = { ok: true, categories: [] }
          else if (url.pathname.endsWith('/genjutsu')) data = { ok: true, visible: false }
          else if (url.pathname.endsWith('/wan3/repeat-plan')) data = { ok: true, source_feed_gen_id: 777,
            repeat_plan_hash: 'synthetic-hash', recipe: { model, scenario: 'text', prompt: '',
              resolution: '720P', aspect_ratio: '16:9', duration: 5, audio: true, nsfw_checker: true },
            slots: [], ...(admin ? { repeat_user_fields: fields } : {}) }
          else if (url.pathname.endsWith('/wan3/quote')) {
            quotes.push(route.request().postDataJSON())
            data = { ok: true, quote_hash: 'synthetic-quote', reserve_cost: 0, admin_free: true }
          } else if (/generate|remix|payment|share/.test(url.pathname)) {
            mutations.push(url.pathname); data = { ok: false, error: 'Blocked synthetic mutation' }
          }
          return route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
        }
        return url.origin === origin ? route.continue() : route.abort()
      })
      await page.goto(base + '?startapp=remix_777', { waitUntil: 'networkidle' })
      await page.locator('textarea').first().waitFor()
      if (admin) {
        await page.getByRole('button', { name: 'red dress', exact: true }).click()
        assert.equal(await page.getByRole('button', { name: 'red dress', exact: true }).getAttribute('aria-pressed'), 'true')
        if (model.startsWith('wan_')) {
          await page.waitForFunction(() => document.querySelector('[aria-pressed="true"]') != null)
          await new Promise(resolve => setTimeout(resolve, 600))
          assert.ok(quotes.some(body => body.recipe.repeat_user_values?.clothes === 'red dress'), 'WAN wire carries selected choice')
        }
      } else {
        assert.equal(await page.getByRole('button', { name: 'red dress', exact: true }).count(), 0)
        assert.equal(await page.getByText('Что заменить в работе', { exact: true }).count(), 0)
      }
      assert.deepEqual(errors, [])
      assert.deepEqual(mutations, [])
      console.log('PASS ' + (admin ? 'admin ' : 'ordinary ') + model + ': safe fields and choices')
      await context.close()
    }
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
