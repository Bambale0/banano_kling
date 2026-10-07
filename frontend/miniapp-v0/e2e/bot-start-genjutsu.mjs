import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

const port = Number(process.env.BOT_START_GENJUTSU_E2E_PORT || 4196)
const origin = 'http://127.0.0.1:' + port
const baseUrl = origin + '/mini-app/'
const root = mkdtempSync(join(tmpdir(), 'bot-start-genjutsu-e2e-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const capability = { label: 'Genjutsu', resolutions: ['720p'], min_images: 1, max_images: 8, max_prompt_length: 4000,
  minimum_video_ms: 4000, maximum_video_ms: 30000, roles: ['character', 'style'] }
const recipe = { id: 'a'.repeat(32), title: 'Мой танец', source_slot: { kind: 'video', label: 'Видео-референс' },
  slots: [{ step_index: 0, reference_index: 0, role: 'character', label: 'Фото героя' }], user_fields: [],
  steps: [{ operation: 'motion_transfer', resolution: '720p' }], variants: 2, continuation: 'automatic', current_cost: 40 }
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
  for (const query of ['?genjutsu=1', '?startapp=genjutsu', '?startapp=prompt_77', '?startapp=genjutsu_recipe_' + recipe.id]) {
    const context = await browser.newContext({ viewport: { width: 390, height: 900 }, serviceWorkers: 'block' })
    const page = await context.newPage()
    page.setDefaultTimeout(8000)
    const forbidden = [], errors = []
    const started = false
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => {
      window.__opened = []
      window.Telegram = { WebApp: { initData: 'query_id=genjutsu-offer-e2e', initDataUnsafe: {}, ready() {}, expand() {},
        openTelegramLink(url) { window.__opened.push(url) }, requestWriteAccess() { throw Error('native permission called') },
        onEvent(name, handler) { window.addEventListener('fixture:' + name, handler) },
        offEvent(name, handler) { window.removeEventListener('fixture:' + name, handler) } } }
    })
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// mock' })
      if (url.pathname.includes('/mini-app/api/')) {
        const body = JSON.parse(request.postData() || '{}'), path = url.pathname.split('/api/')[1]
        let response = { ok: true }
        if (path === 'bootstrap') response = { ...bootstrap, telegram_chat_available: started, telegram_bot_start_required: !started }
        else if (path === 'prompts/detail') response = { ok: true, prompt: { id: 77, title: 'Recipe link', model: 'genjutsu', category: 'video', tags: ['trend'], generation_settings: { genjutsu_recipe_id: recipe.id } } }
        else if (path === 'prompts') response = { ok: true, prompts: [] }
        else if (path === 'genjutsu' && body.action === 'availability') response = { ok: true, visible: true }
        else if (path === 'genjutsu' && body.action === 'bootstrap') response = { ok: true, catalog: { motion_transfer: capability, object_swap: capability, restyle: capability }, configured: true, enabled: true, is_admin: false, provider_ready: true, media_ready: true, credits: 125, config_version: 1, limits: { max_steps: 3, max_variants: 4, poll_seconds: 5 }, prices: {}, projects: [], runs: [], assets: [] }
        else if (path === 'genjutsu' && body.action === 'recipe_preview') response = { ok: true, card: null }
        else if (path === 'genjutsu' && body.action === 'recipe_get') response = { ok: true, recipe }
        else if (path !== 'client-log') { forbidden.push({ path, action: body.action }); response = { ok: false } }
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) })
      }
      if (url.origin === origin) return route.continue()
      forbidden.push(url.href); return route.abort()
    })
    await page.goto(baseUrl + query)
    const region = page.getByRole('region', { name: 'Студия Genjutsu' })
    await region.waitFor()
    await page.waitForLoadState('networkidle')
    const gate = page.locator('[role="dialog"][aria-labelledby="bot-write-access-title"]')
    assert.equal(await gate.count(), 0, 'Genjutsu must not be covered by optional delivery modal: ' + query)
    if (query === '?genjutsu=1') {
      mkdirSync('test-results', { recursive: true })
      await page.screenshot({ path: 'test-results/bot-start-genjutsu-390.png' })
    }
    const draft = region.locator('textarea').first()
    if (await draft.count()) {
      await draft.fill('Keep Genjutsu draft during optional delivery deferral')
      const node = await draft.elementHandle()
      await page.evaluate(() => {
        window.dispatchEvent(new Event('focus'))
        window.dispatchEvent(new Event('fixture:activated'))
        document.dispatchEvent(new Event('visibilitychange'))
      })
      await page.waitForLoadState('networkidle')
      assert.equal(await node.evaluate(el => el.isConnected), true)
      assert.equal(await draft.inputValue(), 'Keep Genjutsu draft during optional delivery deferral')
      assert.equal(await gate.count(), 0)
      await node.dispose()
    }
    await region.getByRole('button', { name: 'Закрыть студию' }).click()
    await region.waitFor({ state: 'hidden' })
    await gate.waitFor()
    await gate.getByRole('button', { name: 'Открыть бота', exact: true }).click()
    assert.equal((await page.evaluate(() => window.__opened)).length, 1)
    await gate.getByRole('button', { name: 'Пропустить', exact: true }).click()
    await gate.waitFor({ state: 'hidden' })
    await page.getByRole('button', { name: 'Получать в боте', exact: true }).waitFor()
    await page.evaluate(id => window.dispatchEvent(new CustomEvent('genjutsu:open', { detail: { recipe_id: id } })), recipe.id)
    await region.getByText(recipe.title, { exact: true }).waitFor()
    assert.equal(await gate.count(), 0)
    await region.getByRole('button', { name: 'Закрыть студию' }).click()
    await region.waitFor({ state: 'hidden' })
    assert.equal(await gate.count(), 0, 'Skip stays dismissed after studio reopens/closes')
    assert.deepEqual(forbidden, []); assert.deepEqual(errors, [])
    console.log('PASS Genjutsu optional modal deferral: ' + query)
    await context.close()
  }
} finally { await browser?.close(); server.kill('SIGTERM'); rmSync(root, { recursive: true, force: true }) }
