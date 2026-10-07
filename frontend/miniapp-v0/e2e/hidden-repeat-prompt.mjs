import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

// This isolated static export uses synthetic, deliberately inconsistent cards.
// All external requests and generation endpoints are intercepted, never live.
const port = Number(process.env.HIDDEN_REPEAT_E2E_PORT || 4187)
const origin = 'http://127.0.0.1:' + port
const baseUrl = origin + '/mini-app/'
const root = mkdtempSync(join(tmpdir(), 'hidden-repeat-e2e-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const media = readFileSync(new URL('./fixtures/genjutsu-result.mp4', import.meta.url))
const secret = 'SYNTHETIC_PRIVATE_REPEAT_RECIPE'
const card = { id: 777, task_id: 'synthetic-repeat', model: 'v3_pro', gen_type: 'video',
  result_url: 'https://example.test/result.mp4', preview_url: 'https://example.test/result.mp4',
  result_urls: ['https://example.test/result.mp4'], prompt: secret, prompt_hidden: true, prompt_actions_allowed: false,
  reference_images: [], reference_videos: [], references_hidden: true, feed_references_visible: false,
  likes_count: 0, shares_count: 0, comments_count: 0, aspect_ratio: '16:9', duration: 5, scenario: 'text',
  author: 'E2E Owner', author_referral_code: 'E2EOWNER', is_mine: true, is_profile_visible: true,
  publication_scope: 'feed', feed_interactions_enabled: true, remixes: 0, score: 0, created_at: '2026-10-07T00:00:00Z' }
const bootstrap = { ok: true, telegram_id: 424242, first_name: 'E2E', last_name: 'Owner', telegram_username: 'e2e_owner',
  photo_url: '', referral_code: 'E2EOWNER', profile_link: '', referral_link: '', channel_url: '',
  prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0, bot_username: 'test_bot', credits: 125, is_admin: false,
  mini_app_url: baseUrl, actions: [], payment_packages: [], image_models: [],
  video_models: [{ id: 'v3_pro', label: 'Video model', description: 'Synthetic', durations: [5], ratios: ['16:9'], supports: ['text'], costs: { '5': 5 } }],
  recent_tasks: [], saved_references: [] }
let browser
try {
  const deadline = Date.now() + 20000
  while (true) {
    try { if ((await fetch(baseUrl)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static export unavailable')
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ headless: true })
  for (const width of [360, 430]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage()
    const forbidden = []
    const errors = []
    let currentCard = card
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => {
      window.Telegram = { WebApp: { initData: 'query_id=hidden-repeat-e2e', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
    })
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// fixture' })
      if (url.hostname === 'example.test') return route.fulfill({ contentType: 'video/mp4', body: media })
      if (url.pathname.includes('/mini-app/api/')) {
        let response = { ok: true }
        if (url.pathname.endsWith('/bootstrap')) response = bootstrap
        else if (url.pathname.endsWith('/feed/item')) response = { ok: true, feed_item: currentCard }
        else if (url.pathname.endsWith('/feed/profile')) response = { ok: true, feed: [currentCard], profile: { name: 'E2E Owner', first_name: 'E2E', referral_code: 'E2EOWNER', posts_count: 1 } }
        else if (url.pathname.endsWith('/feed') || url.pathname.endsWith('/feed/my')) response = { ok: true, feed: [currentCard], models: [{ id: 'v3_pro', label: 'Video model' }] }
        else if (url.pathname.endsWith('/prompts')) response = { ok: true, prompts: [] }
        else if (url.pathname.endsWith('/genjutsu')) response = { ok: true, visible: false }
        else if (/generate|repeat|remix|start/.test(url.pathname)) { forbidden.push(url.pathname); response = { ok: false } }
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) })
      }
      if (url.origin === origin) return route.continue()
      return route.abort()
    })
    for (const surface of ['Лента', 'Профиль', 'deep-link']) {
      await page.goto(baseUrl + (surface === 'deep-link' ? '?startapp=remix_777' : ''))
      await page.waitForLoadState('networkidle')
      if (surface !== 'deep-link') {
        await page.getByRole('button', { name: surface, exact: true }).click()
        await page.getByRole('button', { name: surface === 'Лента' ? 'Открыть видео' : 'Открыть публикацию' }).first().click()
        await page.getByRole('button', { name: /^Повторить(?: · [0-9]+)?$/ }).click()
      }
      const textbox = page.locator('textarea').first()
      await textbox.waitFor()
      assert.equal(await textbox.inputValue(), '', surface + ': hidden prompt stays empty')
      assert.equal((await page.locator('body').innerText()).includes(secret), false)
      await textbox.fill('My additional instruction')
      await page.getByRole('button', { name: 'Лента', exact: true }).click()
      await page.getByRole('button', { name: 'Открыть видео' }).first().click()
      await page.getByRole('button', { name: /^Повторить$/ }).click()
      assert.equal(await textbox.inputValue(), '', surface + ': reopening clears stale source text and previous edits')
    }
    currentCard = { ...card, prompt: 'Ordinary owner instruction', prompt_hidden: false, prompt_actions_allowed: true }
    await page.goto(baseUrl + '?startapp=remix_777')
    await page.waitForLoadState('networkidle')
    await page.getByText('Повторить видео из ссылки', { exact: true }).waitFor()
    await page.waitForFunction(expected => document.querySelector('textarea')?.value === expected, currentCard.prompt)
    assert.equal(await page.locator('textarea').first().inputValue(), currentCard.prompt, 'Visible owner prompt remains usable')
    assert.deepEqual(forbidden, [], 'No generation/publication calls')
    assert.deepEqual(errors, [], 'No browser errors')
    console.log('PASS ' + width + 'px: Feed/Profile/deep-link hidden stale cards, reopen, ordinary owner control')
    await context.close()
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
