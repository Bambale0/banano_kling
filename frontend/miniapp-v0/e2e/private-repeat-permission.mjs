import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

// Run against this worktree's static export. Every API/media request is mocked;
// no real account, publication, provider generation, or production server is used.
const port = Number(process.env.PRIVATE_REPEAT_E2E_PORT || 4174)
const baseUrl = `http://127.0.0.1:${port}/mini-app/`
const serverRoot = mkdtempSync(join(tmpdir(), 'private-repeat-e2e-'))
symlinkSync(resolve('out'), join(serverRoot, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', serverRoot], { stdio: 'ignore' })
let browser

const task = {
  task_id: 'private-repeat-e2e', type: 'image', model: 'banana_pro',
  model_label: 'Nano Banana Pro', aspect_ratio: '1:1', status: 'completed',
  result_url: 'https://example.test/result.png', created_at: '2026-10-03T00:00:00Z',
  prompt: 'Private repeat E2E portrait', prompt_preview: 'Private repeat E2E portrait',
  cost: 1, publication_reference_images: ['https://example.test/face.png', 'https://example.test/outfit.png'],
  publication_reference_image_indices: [1, 4],
}
const bootstrap = {
  ok: true, telegram_id: 424242, first_name: 'E2E', last_name: 'Owner',
  telegram_username: 'e2e_owner', photo_url: '', referral_code: 'E2EOWNER',
  profile_link: '', referral_link: '', channel_url: '', prompt_repeat_balance_rub: 0,
  prompt_repeat_total_rub: 0, bot_username: 'test_bot', credits: 125, is_admin: false,
  mini_app_url: baseUrl, actions: [], payment_packages: [],
  image_models: [{ id: 'banana_pro', label: 'Nano Banana Pro', description: 'Image model', cost: 1,
    ratios: ['1:1'], requires_reference: false, max_references: 8, qualities: ['1K'] }],
  video_models: [], recent_tasks: [task], saved_references: [],
}

try {
  const deadline = Date.now() + 20_000
  while (true) {
    if (server.exitCode !== null) throw new Error(`Static server exited: ${server.exitCode}`)
    try {
      if ((await fetch(baseUrl)).ok) break
    } catch {}
    if (Date.now() >= deadline) throw new Error('Static export server did not start')
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ headless: true })
  for (const width of [320, 375, 390, 430]) {
    const context = await browser.newContext({ viewport: { width, height: 900 } })
    const page = await context.newPage()
    const errors = []
    const requests = []
    const ownerTask = { ...task }
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('dialog', (dialog) => dialog.accept())
    await page.addInitScript(() => {
      window.Telegram = { WebApp: {
        initData: 'query_id=private-repeat-e2e', initDataUnsafe: {},
        ready() {}, expand() {}, onEvent() {}, offEvent() {},
      } }
    })
    await page.route('**/telegram-web-app.js', (route) => route.fulfill({
      status: 200, contentType: 'application/javascript', body: '// deterministic test bridge',
    }))
    await page.route('https://example.test/**', (route) => route.fulfill({
      status: 200, contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160"><rect width="160" height="160" fill="#365d71"/><circle cx="80" cy="75" r="40" fill="#9ebdce"/></svg>',
    }))
    await page.route('**/mini-app/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      let response = { ok: true }
      if (path.endsWith('/bootstrap')) response = { ...bootstrap, recent_tasks: [ownerTask] }
      else if (path.endsWith('/task-detail')) response = { ok: true, task: ownerTask }
      else if (path.endsWith('/generations/share')) {
        const payload = JSON.parse(route.request().postData())
        requests.push(payload)
        Object.assign(ownerTask, {
          is_public_feed: true, is_profile_visible: true, publication_scope: 'feed',
          feed_references_visible: payload.references_visible,
          feed_reference_selection: { images: payload.reference_image_indices, videos: payload.reference_video_indices },
          feed_repeat_reference_selection: { images: payload.repeat_reference_image_indices },
        })
        response = { ok: true, feed_item: {
          id: 1, task_id: ownerTask.task_id, model: 'banana_pro', gen_type: 'image',
          result_url: task.result_url, preview_url: task.result_url, result_urls: [task.result_url],
          likes_count: 0, shares_count: 0, remixes: 0, score: 0, references_count: 0,
          created_at: task.created_at, is_mine: true, author: 'E2E Owner',
          publication_scope: 'feed', feed_interactions_enabled: true,
          feed_references_visible: payload.references_visible, feed_blurred: false,
        } }
      } else if (path.endsWith('/feed/remove')) {
        Object.assign(ownerTask, {
          is_public_feed: false, is_profile_visible: false, publication_scope: 'private',
          feed_repeat_reference_selection: { images: [] },
        })
        response = { ok: true, removed: true }
      } else if (path.endsWith('/feed')) response = { ok: true, items: [], has_more: false }
      else if (path.endsWith('/prompts')) response = { ok: true, prompts: [] }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) })
    })

    await page.goto(baseUrl)
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: 'Студия', exact: true }).click()
    await page.getByRole('button', { name: /Private repeat E2E portrait/ }).click()
    await page.getByRole('button', { name: 'Опубликовать', exact: true }).click()
    const selection = page.getByRole('checkbox', { name: 'Фото-референс 2 для повторов' })
    assert.equal(await selection.getAttribute('aria-checked'), 'false')
    await selection.click()
    assert.equal(await selection.getAttribute('aria-checked'), 'true')
    const group = page.getByRole('group', { name: 'Референсы для повторов' })
    await group.scrollIntoViewIfNeeded()
    const bounds = await group.boundingBox()
    assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= width + 1, `Permission group overflows width ${width}`)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
    if (width === 390) {
      mkdirSync('test-results', { recursive: true })
      await page.screenshot({ path: 'test-results/private-repeat-permission-390.png', fullPage: true })
    }
    await page.getByRole('button', { name: 'Опубликовать', exact: true }).first().click()
    await page.getByRole('button', { name: 'Настроить публикацию', exact: true }).waitFor()
    assert.equal(requests.length, 1)
    assert.equal(requests[0].references_visible, false)
    assert.deepEqual(requests[0].repeat_reference_image_indices, [4])
    assert.deepEqual(requests[0].reference_image_indices, [1, 4])

    await page.getByRole('button', { name: 'Настроить публикацию', exact: true }).click()
    assert.equal(await selection.getAttribute('aria-checked'), 'true')
    await page.getByRole('button', { name: 'Снять выбор', exact: true }).click()
    await page.getByRole('button', { name: 'Сохранить публикацию', exact: true }).click()
    await page.getByRole('group', { name: 'Референсы для повторов' }).waitFor({ state: 'hidden' })
    assert.equal(requests.length, 2)
    assert.deepEqual(requests[1].repeat_reference_image_indices, [])
    assert.equal(requests[1].references_visible, false)
    await page.getByRole('button', { name: 'Настроить публикацию', exact: true }).click()
    await page.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }).click()
    await page.getByRole('button', { name: 'Сохранить публикацию', exact: true }).click()
    await group.waitFor({ state: 'hidden' })
    assert.deepEqual(requests[2].repeat_reference_image_indices, [1])
    await page.getByRole('button', { name: 'Настроить публикацию', exact: true }).click()
    await page.getByRole('button', { name: 'Убрать публикацию', exact: true }).click()
    await page.getByRole('button', { name: 'Опубликовать', exact: true }).waitFor()
    await page.getByRole('button', { name: 'Опубликовать', exact: true }).click()
    assert.equal(await page.getByRole('checkbox', { name: 'Фото-референс 1 для повторов' }).getAttribute('aria-checked'), 'false')
    await page.getByRole('button', { name: 'Опубликовать', exact: true }).first().click()
    await page.getByRole('button', { name: 'Настроить публикацию', exact: true }).waitFor()
    assert.equal(requests.length, 4)
    assert.deepEqual(requests[3].repeat_reference_image_indices, [])
    assert.deepEqual(errors, [], `Browser errors at width ${width}`)
    console.log(`PASS ${width}px: off by default, explicit source-index grant, independent hidden display, saved consent restoration, empty-selection revoke, unpublish/re-publish clears consent, no overflow or page errors`)
    await context.close()
  }
} finally {
  if (browser) await browser.close()
  server.kill('SIGTERM')
  rmSync(serverRoot, { recursive: true, force: true })
}
