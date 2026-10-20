import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

// Only synthetic Telegram auth/API responses. This must never create paid jobs.
const port = Number(process.env.BOOT_E2E_PORT || 4263)
const origin = `http://127.0.0.1:${port}`
const root = mkdtempSync(join(tmpdir(), 'tanya-boot-e2e-'))
symlinkSync(resolve(process.env.BOOT_E2E_DIST || 'out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
let browser
try {
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${origin}/mini-app/`)).ok) break } catch {}
    if (i === 99) throw new Error('Static server failed to start')
    await new Promise(done => setTimeout(done, 100))
  }
  browser = await chromium.launch({ headless: true })
  const cases = process.env.BOOT_E2E_CASE ? [process.env.BOOT_E2E_CASE] : ['normal', 'transient', 'persistent', 'stall', 'slow-success', 'bootstrap-timeout']
  for (const scenario of cases) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } })
    const page = await context.newPage()
    const errors = [], telemetry = [], launches = []
    let chunks = 0, bootstraps = 0, allow = false
    const stallReleases = []
    const releaseStall = () => { stallReleases.splice(0).forEach(done => done()) }
    page.on('pageerror', error => errors.push(error.message))
    page.on('console', message => { if (message.type() === 'error' && /hydration|Minified React error #418/i.test(message.text())) errors.push(message.text()) })
    await page.addInitScript(() => {
      window.Telegram = { WebApp: { initData: 'query_id=synthetic-startup', initDataUnsafe: {}, ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
    })
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url())
      if (url.origin !== origin) return route.abort()
      if (url.pathname.endsWith('/telegram-web-app.js')) return route.fulfill({ contentType: 'application/javascript', body: '// synthetic Telegram SDK' })
      if (/\/chunks\/app\/page-[^/]+\.js$/.test(url.pathname)) {
        chunks++
        if (scenario === 'transient' && chunks === 1) return route.abort('connectionreset')
        if (scenario === 'persistent') return route.abort('connectionreset')
        if ((scenario === 'stall' || scenario === 'slow-success') && !allow) {
          await new Promise(done => { stallReleases.push(done) })
          try { return await route.continue() } catch { return }
        }
      }
      if (!url.pathname.includes('/api/')) return route.continue()
      if (url.pathname.endsWith('/client-log')) {
        telemetry.push(request.postDataJSON())
        return route.fulfill({ json: { ok: true } })
      }
      if (/launch|generate/.test(url.pathname)) launches.push(url.pathname)
      if (url.pathname.endsWith('/bootstrap')) {
        bootstraps++
        if (scenario === 'bootstrap-timeout' && !allow) {
          await new Promise(done => { stallReleases.push(done) })
        }
        try { return await route.fulfill({ json: { ok: true, telegram_id: 424242, first_name: 'Synthetic', credits: 0, is_admin: false,
          bot_username: 'synthetic_bot', recent_tasks: [], saved_references: [], image_models: [], video_models: [], payment_packages: [], actions: [] } }) } catch { return }
      }
      return route.fulfill({ json: { ok: true, visible: false, feed: [], models: [], prompts: [], tasks: [] } })
    })
    const hash = '#tgWebAppData=query_id%3Dsynthetic-startup&tgWebAppStartParam=boot_referral'
    await page.goto(`${origin}/mini-app/?startapp=boot_referral${hash}`, { waitUntil: 'commit' })
    if (scenario === 'persistent' || scenario === 'stall' || scenario === 'slow-success') {
      const recovery = page.locator('#miniapp-startup-recovery')
      try { await recovery.waitFor({ state: 'visible', timeout: 20_000 }) }
      catch (e) {
        console.log('RECOVERY_DIAGNOSTIC', await page.evaluate(() => ({
          readyState: document.readyState, guard: typeof window.__BANANO_BOOT_RECOVERY__,
          panel: document.getElementById('miniapp-startup-recovery')?.outerHTML,
          bodyText: document.body.innerText.slice(-700),
        })), { errors, chunks, bootstraps, telemetry })
        throw e
      }
      assert.equal(bootstraps, 0)
      if (scenario === 'persistent') {
        assert.ok(chunks <= 3, 'no unbounded competing chunk retries')
        assert.equal(await page.locator('#miniapp-startup-recovery button').count(), 1)
      } else if (scenario === 'slow-success') {
        allow = true
        releaseStall()
        await page.getByRole('button', { name: 'Студия', exact: true }).waitFor({ timeout: 10_000 })
        assert.ok(bootstraps > 0)
        assert.equal(await recovery.isVisible(), false)
        assert.equal(new URL(page.url()).searchParams.has('_boot_reload'), false)
      } else {
        allow = true
        const navigated = page.waitForURL(url => url.searchParams.has('_boot_reload'), { waitUntil: 'commit', timeout: 10_000 })
        await recovery.getByRole('button', { name: 'Повторить загрузку' }).click()
        await navigated
        releaseStall()
        await page.getByRole('button', { name: 'Студия', exact: true }).waitFor({ timeout: 10_000 })
        const restored = new URL(page.url())
        assert.equal(restored.searchParams.get('startapp'), 'boot_referral')
        assert.equal(restored.hash, hash)
        assert.ok(bootstraps > 0)
        assert.equal(await recovery.isVisible(), false)
      }
    } else if (scenario === 'bootstrap-timeout') {
      await page.getByRole('button', { name: 'Повторить подключение' }).waitFor({ timeout: 20_000 })
      assert.equal(bootstraps, 1)
      allow = true
      releaseStall()
      await page.getByRole('button', { name: 'Повторить подключение' }).click()
      await page.getByRole('button', { name: 'Студия', exact: true }).waitFor({ timeout: 10_000 })
    } else {
      await page.getByRole('button', { name: 'Студия', exact: true }).waitFor({ timeout: 10_000 })
      assert.ok(bootstraps > 0, 'the app must leave SSR and request bootstrap')
      if (scenario === 'transient') assert.equal(chunks, 2, 'retry the failed entry script without reloading')
    }
    assert.equal(launches.length, 0, 'recovery never submits a generation')
    const unexpectedErrors = errors.filter(error => !(scenario === 'persistent' && /^Loading chunk .* failed/.test(error)))
    assert.equal(unexpectedErrors.length, 0, unexpectedErrors.join('\n'))
    assert.ok(!JSON.stringify(telemetry).includes('query_id'), 'never log Telegram auth')
    console.log(`${scenario}: passed; entry requests=${chunks}, bootstrap requests=${bootstraps}`)
    await context.close()
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
