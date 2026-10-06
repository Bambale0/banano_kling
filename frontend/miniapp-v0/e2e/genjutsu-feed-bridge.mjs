import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

const port = Number(process.env.GENJUTSU_FEED_E2E_PORT || 4179)
const origin = 'http://127.0.0.1:' + port
const baseUrl = origin + '/mini-app/'
const root = mkdtempSync(join(tmpdir(), 'genjutsu-feed-e2e-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
// One-second synthetic navy clip; no encoder or network is required in CI.
const media = readFileSync(new URL('./fixtures/genjutsu-result.mp4', import.meta.url))
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a++sAAAAASUVORK5CYII=', 'base64')
const asset = { id: 'output', kind: 'video', url: 'https://example.test/result.mp4', duration_ms: 5000 }
const step = { operation: 'motion_transfer', resolution: '720p', prompt: 'Owner-only prompt', preserve: '', preset_id: null, references: [
  { asset_id: 'hidden-face', role: 'character', label: 'Фото героя', binding: 'user' },
  { asset_id: 'hidden-style', role: 'style', label: 'Стиль', binding: 'fixed' },
] }
const run = { id: 'completed-run', owner: 424242, state: 'completed', private_recipe: 0, admin_free: 0, cancel_requested: 0, credits: 125, created_ms: Date.now(),
  plan: { source_asset_id: 'hidden-video', steps: [step], variants: 2, continuation: 'automatic' },
  steps: [0, 1].map(variant => ({ id: 'step-' + variant, variant, ordinal: 0, status: 'completed', spec: step, reserved_credits: 20, actual_credits: 20,
    refunded_credits: 0, error_code: null, delivery_status: null, delivery_error: null, output_asset: asset })),
}
const capability = { label: 'Genjutsu', resolutions: ['720p'], min_images: 1, max_images: 8, max_prompt_length: 4000,
  minimum_video_ms: 4000, maximum_video_ms: 30000, roles: ['character', 'style'] }
const recipe = { id: 'a'.repeat(32), title: 'Мой танец', source_slot: { kind: 'video', label: 'Видео-референс' },
  slots: [{ step_index: 0, reference_index: 0, role: 'character', label: 'Фото героя' }], user_fields: [],
  steps: [{ operation: 'motion_transfer', resolution: '720p' }], variants: 2, continuation: 'automatic', current_cost: 40 }
const card = { id: 777, task_id: 'genjutsu-output', model: 'genjutsu', gen_type: 'video', genjutsu_recipe_id: recipe.id,
  result_url: asset.url, preview_url: asset.url, result_urls: [asset.url], prompt: '', prompt_hidden: true,
  reference_images: [], reference_videos: [], references_hidden: true, feed_references_visible: false,
  likes_count: 0, shares_count: 0, comments_count: 0, aspect_ratio: '9:16', author: 'E2E Owner', author_referral_code: 'E2EOWNER',
  is_mine: true, is_profile_visible: true, publication_scope: 'feed', feed_interactions_enabled: true, can_remove: true,
  remixes: 0, score: 0, created_at: '2026-10-05T00:00:00Z' }
const bootstrap = { ok: true, telegram_id: 424242, first_name: 'E2E', last_name: 'Owner', telegram_username: 'e2e_owner',
  photo_url: '', referral_code: 'E2EOWNER', profile_link: '', referral_link: '', channel_url: '',
  prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0, bot_username: 'test_bot', credits: 125, is_admin: false,
  mini_app_url: baseUrl, actions: [], payment_packages: [], image_models: [], video_models: [], recent_tasks: [], saved_references: [] }
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
    const errors = []
    const requests = []
    const forbidden = []
    let published = false
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => {
      window.Telegram = { WebApp: { initData: 'query_id=genjutsu-feed-e2e', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
    })
    // Deny every nonfixture external request. All account/API mutations stay synthetic.
    await page.route('**/*', async route => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// test bridge' })
      if (url.hostname === 'example.test') return route.fulfill({
        contentType: url.pathname.endsWith('.mp4') ? 'video/mp4' : 'image/png',
        body: url.pathname.endsWith('.mp4') ? media : image,
      })
      if (url.pathname.includes('/mini-app/api/')) {
        const body = request.method() === 'POST' && request.headers()['content-type']?.includes('application/json') ? JSON.parse(request.postData() || '{}') : {}
        requests.push({ path: url.pathname, ...body })
        let response = { ok: true }
        if (url.pathname.endsWith('/genjutsu/upload')) response = { ok: true, asset: url.searchParams.get('kind') === 'video'
          ? { ...asset, id: 'own-video', url: 'https://example.test/own-video.mp4' }
          : { id: 'own-photo', kind: 'image', url: 'https://example.test/own-photo.png' } }
        else if (url.pathname.endsWith('/genjutsu')) {
          if (body.action === 'availability') response = { ok: true, visible: true }
          else if (body.action === 'bootstrap') response = { ok: true, catalog: { motion_transfer: capability, object_swap: capability, restyle: capability },
            configured: true, enabled: true, is_admin: false, provider_ready: true, media_ready: true, credits: 125, config_version: 1,
            limits: { max_steps: 3, max_variants: 4, poll_seconds: 5 }, prices: {}, projects: [], runs: [{ id: run.id, state: run.state, created_ms: run.created_ms }], assets: [] }
          else if (body.action === 'run') response = { ok: true, run }
          else if (body.action === 'feed_publish') { published = true; response = { ok: true, card, recipe } }
          else if (body.action === 'recipe_get') response = { ok: true, recipe }
          else if (body.action === 'recipe_quote') response = { ok: true, recipe, quote: { id: 'own-quote', expires_ms: Date.now() + 300000, total_credits: 56, allocations: [], plan_hash: 'private' } }
          else { forbidden.push(body.action); response = { ok: false, error: 'Unexpected action' } }
        } else if (url.pathname.endsWith('/bootstrap')) response = bootstrap
        else if (url.pathname.endsWith('/feed/profile')) response = { ok: true, feed: published ? [card] : [], profile: { name: 'E2E Owner', first_name: 'E2E', referral_code: 'E2EOWNER', posts_count: 1 } }
        else if (url.pathname.endsWith('/feed') || url.pathname.endsWith('/feed/my')) response = { ok: true, feed: published ? [card] : [], models: [{ id: 'genjutsu', label: 'Higgsfield Genjutsu' }] }
        else if (url.pathname.endsWith('/prompts')) response = { ok: true, prompts: [] }
        else if (/generate|repeat|remix|start/.test(url.pathname)) { forbidden.push(url.pathname); response = { ok: false } }
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) })
      }
      if (url.origin === origin) return route.continue()
      return route.abort()
    })
    await page.goto(baseUrl)
    await page.waitForLoadState('networkidle')
    await page.evaluate(id => window.dispatchEvent(new CustomEvent('genjutsu:open', { detail: { run_id: id } })), run.id)
    const region = page.getByRole('region', { name: 'Студия Genjutsu' })
    await region.getByText(run.id, { exact: true }).waitFor()
    assert.equal(await region.getByRole('button', { name: 'Опубликовать в ленту', exact: true }).count(), 2)
    await region.getByRole('button', { name: 'Опубликовать в ленту', exact: true }).first().click()
    const publisher = region.getByRole('region', { name: 'Публикация Genjutsu' })
    await publisher.getByLabel('Название публикации').fill(recipe.title)
    for (const input of [publisher.getByLabel('Название публикации'), publisher.getByLabel('Видео при повторе')]) {
      const bounds = await input.boundingBox()
      assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= width + 1, 'Publisher fields stay within phone width')
    }
    await publisher.getByLabel('Видео при повторе').selectOption('fixed')
    await publisher.getByText('Повтор использует исходное видео автора. Оно скрыто и не заменяется.').waitFor()
    await publisher.getByRole('button', { name: 'Отмена', exact: true }).click()
    assert.equal(requests.filter(item => item.action === 'feed_publish').length, 0)
    await region.getByRole('button', { name: 'Опубликовать в ленту', exact: true }).first().click()
    assert.equal(await publisher.getByLabel('Видео при повторе').inputValue(), 'fixed')
    await publisher.getByLabel('Видео при повторе').selectOption('user')
    assert.equal(await publisher.evaluate(el => el.scrollWidth <= el.clientWidth), true, 'Publisher fits ' + width)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    if (width === 360) {
      mkdirSync('test-results', { recursive: true })
      await publisher.scrollIntoViewIfNeeded()
      await page.screenshot({ path: 'test-results/genjutsu-publisher-360.png', fullPage: true })
    }
    await publisher.getByRole('button', { name: 'Опубликовать результат', exact: true }).click()
    await region.getByText('Опубликовано в ленте', { exact: true }).waitFor()
    const publication = requests.filter(item => item.action === 'feed_publish')
    assert.equal(publication.length, 1)
    assert.equal(publication[0].source_binding, 'user')
    assert.equal(publication[0].step_id, 'step-0')
    assert.equal(publication[0].title, recipe.title)
    assert.equal('plan' in publication[0], false)
    await region.getByRole('button', { name: 'Закрыть студию' }).click()
    await region.waitFor({ state: 'hidden' })
    for (const surface of ['Лента', 'Профиль']) {
      await page.getByRole('button', { name: surface, exact: true }).click()
      try {
        await page.getByRole('button', { name: surface === 'Лента' ? 'Открыть видео' : 'Открыть публикацию' }).first().click({ timeout: 10000 })
      } catch (error) {
        console.log('DIAGNOSTIC', surface, errors, requests.slice(-8), await page.locator('body').innerText())
        throw error
      }
      await page.getByRole('button', { name: /^Повторить(?: · [0-9]+)?$/ }).click()
      await region.getByText(recipe.title, { exact: true }).waitFor()
      assert.equal(await region.locator('textarea').count(), 0, 'Hidden recipe does not expose prompts')
      assert.equal(await region.getByLabel('Стиль', { exact: true }).count(), 0, 'Fixed original remains hidden')
      const quote = region.getByRole('button', { name: 'Рассчитать стоимость', exact: true })
      assert.equal(await quote.isEnabled(), false)
      await region.getByLabel('Видео-референс', { exact: true }).setInputFiles({ name: 'own.mp4', mimeType: 'video/mp4', buffer: media })
      await region.getByText('Видео загружено — нажмите, чтобы заменить').waitFor()
      assert.equal(await quote.isEnabled(), false)
      await region.getByLabel('Фото героя', { exact: true }).setInputFiles({ name: 'own.png', mimeType: 'image/png', buffer: image })
      await quote.click()
      await region.getByText('56 бананов', { exact: true }).waitFor()
      const submitted = requests.filter(item => item.action === 'recipe_quote').at(-1)
      assert.equal(submitted.recipe_id, recipe.id)
      assert.equal(submitted.source_asset_id, 'own-video')
      assert.deepEqual(submitted.reference_asset_ids, ['own-photo'])
      await region.getByText('Вариантов в повторе: 2. Расчёт включает всю цепочку и все варианты.').waitFor()
      assert.equal(await region.evaluate(el => el.scrollWidth <= el.clientWidth), true)
      if (width === 360) {
        mkdirSync('test-results', { recursive: true })
        await page.screenshot({ path: 'test-results/genjutsu-feed-' + surface + '-360.png', fullPage: true })
      }
      await region.getByRole('button', { name: 'Закрыть студию' }).click()
      await region.waitFor({ state: 'hidden' })
      // The source preview must be dismissed along with the repeat handoff.
      assert.equal(await page.getByRole('button', { name: /^Повторить(?: · [0-9]+)?$/ }).count(), 0)
    }
    assert.deepEqual(forbidden, [], 'No generation or generic repeat API is allowed')
    assert.deepEqual(errors, [], 'No browser errors at ' + width)
    console.log('PASS ' + width + 'px: completed output publication, cancel/reopen source policy, feed/profile repeat, own video+photo server quote, no hidden originals or real generation')
    await context.close()
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
