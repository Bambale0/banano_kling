import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

// Synthetic per-viewer server responses only. Never reach a provider or production API.
const port = 4196
const origin = `http://127.0.0.1:${port}`
const baseUrl = `${origin}/mini-app/`
const root = mkdtempSync(join(tmpdir(), 'creator-tariff-browser-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const rates = { standard: { seedance_2: 4, '480p': 3, '720p': 6 }, creator: { seedance_2: 1.25, '480p': 1.1, '720p': 2.05 } }
// These are deliberately exact fixture totals, including Python's half-step tie behavior.
const totals = { standard: { seedance_2: { 5: 20, 10: 40 }, '480p': { 5: 15, 6: 18 }, '720p': { 5: 30, 6: 36 } },
  creator: { seedance_2: { 5: 6, 10: 12.5 }, '480p': { 5: 5.5, 6: 6.5 }, '720p': { 5: 10, 6: 12.5 } } }
let browser
try {
  const deadline = Date.now() + 20000
  while (true) {
    try { if ((await fetch(baseUrl)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static export unavailable')
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ headless: true })
  for (const profile of ['standard', 'creator']) {
    for (const model of ['seedance_2', 'seedance_2_5']) {
      const context = await browser.newContext({ viewport: { width: 390, height: 900 } })
      const page = await context.newPage()
      const errors = [], requests = []
      page.on('pageerror', error => errors.push(error.message))
      await page.addInitScript(() => {
        window.Telegram = { WebApp: { initData: 'query_id=creator-browser-synthetic', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
      })
      const modelData = { id: model, label: model === 'seedance_2' ? 'Seedance 2.0' : 'Seedance 2.5', description: 'Synthetic pricing',
        durations: model === 'seedance_2' ? [5, 10] : [-1, 4, 5, 6, 30], ratios: ['16:9'], supports: ['text', 'imgtxt', 'video'],
        max_image_references: 9, max_video_references: 3,
        costs: model === 'seedance_2' ? totals[profile].seedance_2 : totals[profile]['720p'],
        quality_costs: model === 'seedance_2' ? { '720p': rates[profile].seedance_2 } : { '480p': rates[profile]['480p'], '720p': rates[profile]['720p'] },
        quality_duration_costs: model === 'seedance_2' ? { '720p': totals[profile].seedance_2 } : { '480p': totals[profile]['480p'], '720p': totals[profile]['720p'] } }
      await page.route('**/*', async route => {
        const url = new URL(route.request().url())
        if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// synthetic' })
        if (url.pathname.includes('/mini-app/api/')) {
          let data = { ok: true }, status = 200
          if (url.pathname.endsWith('/bootstrap')) data = {
            ok: true, telegram_id: profile === 'creator' ? 720002 : 720001, first_name: profile, last_name: '', telegram_username: profile,
            photo_url: '', referral_code: 'SYNTHETIC', profile_link: '', referral_link: '', channel_url: '', bot_username: 'test_bot',
            prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0, credits: 1000, is_admin: false, telegram_chat_available: true,
            mini_app_url: baseUrl, actions: [], payment_packages: [], image_models: [], video_models: [modelData], recent_tasks: [],
            saved_references: [{ id: 'one', kind: 'video', filename: 'synthetic-one.mp4', url: 'https://example.test/one.mp4' },
              { id: 'two', kind: 'video', filename: 'synthetic-two.mp4', url: 'https://example.test/two.mp4' }],
          }
          else if (url.pathname.endsWith('/genjutsu')) data = { ok: true, visible: false }
          else if (url.pathname.endsWith('/feed')) data = { ok: true, feed: [], models: [] }
          else if (url.pathname.endsWith('/prompts')) data = { ok: true, prompts: [] }
          else if (url.pathname.endsWith('/generate-video')) {
            requests.push(route.request().postDataJSON())
            status = 400; data = { ok: false, error: 'Synthetic rejection: no provider request' }
          } else if (/generate|repeat|remix|payment|trends\/run/.test(url.pathname)) throw new Error(`Unexpected mutation ${url.pathname}`)
          return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
        }
        if (url.origin === origin) return route.continue()
        return route.abort()
      })
      await page.goto(baseUrl, { waitUntil: 'networkidle' })
      await page.getByRole('button', { name: 'Видео', exact: true }).click()
      if (model === 'seedance_2') {
        const summary = page.getByText('Стоимость', { exact: true }).locator('..').locator('..')
        await summary.getByText(String(totals[profile].seedance_2[5]), { exact: true }).waitFor()
        await page.getByRole('button', { name: 'Видео + Текст', exact: true }).click()
        await page.getByRole('button', { name: 'synthetic-one.mp4', exact: true }).click()
        await summary.getByText(String(totals[profile].seedance_2[5] * 2), { exact: true }).waitFor()
        await page.getByRole('button', { name: 'synthetic-two.mp4', exact: true }).click()
        await summary.getByText(String(totals[profile].seedance_2[5] * 2), { exact: true }).waitFor()
        await page.getByRole('button', { name: /10с/ }).click()
        await summary.getByText(String(totals[profile].seedance_2[10] * 2), { exact: true }).waitFor()
        await page.locator('textarea').fill('Synthetic motion')
        await page.getByRole('button', { name: /Запустить видео/ }).click()
      } else {
        const summary = page.getByText('Стоимость генерации', { exact: true }).locator('..')
        await summary.getByText(`${totals[profile]['720p'][5]}🍌`, { exact: true }).waitFor()
        await page.getByRole('button', { name: /^480p/ }).click()
        await summary.getByText(`${totals[profile]['480p'][5]}🍌`, { exact: true }).waitFor()
        const duration = page.getByLabel('Длительность видео', { exact: true })
        await duration.focus(); await duration.press('ArrowRight')
        await summary.getByText(`${totals[profile]['480p'][6]}🍌`, { exact: true }).waitFor()
        await page.getByRole('button', { name: /^720p/ }).click()
        await summary.getByText(`${totals[profile]['720p'][6]}🍌`, { exact: true }).waitFor()
        await page.getByText('Для продвинутых: добавить URL или Asset ID', { exact: true }).click()
        await page.getByLabel('Видео — по одному URL / asset:// на строку', { exact: true }).fill('asset://synthetic-one\nasset://synthetic-two')
        await summary.getByText(`${totals[profile]['720p'][6] * 2}🍌`, { exact: true }).waitFor()
        await page.getByLabel('Промпт для Seedance 2.5', { exact: true }).fill('Synthetic motion')
        await page.getByRole('button', { name: /Создать видео ·/ }).click()
      }
      await page.getByText('Synthetic rejection: no provider request', { exact: true }).waitFor()
      assert.equal(requests.length, 1)
      for (const key of ['tariff', 'profile', 'creator_tariff', 'billing_quote', 'charge_cost', 'cost_multiplier']) {
        assert.equal(Object.hasOwn(requests[0], key), false, `Client must not choose ${key}`)
      }
      assert.equal(requests[0].v_model, model)
      assert.equal(requests[0].v_reference_videos.length, 2)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      assert.deepEqual(errors, [])
      // Leaving and reopening resets the compose state; prices remain this viewer's.
      await page.getByRole('button', { name: 'Студия', exact: true }).click()
      await page.getByRole('button', { name: 'Видео', exact: true }).click()
      console.log(`PASS ${profile} ${model}: personal rounded quote, quality/duration, ×2 once, no client tariff, rejected launch and navigation`)
      await context.close()
    }
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
