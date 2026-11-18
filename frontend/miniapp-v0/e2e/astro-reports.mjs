// Synthetic mobile report lifecycle: no real Telegram, provider, user or payments.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { chromium, devices } from 'playwright'

const base = 'http://127.0.0.1:4379'
const server = spawn('python3', ['-m', 'http.server', '4379', '--bind', '127.0.0.1',
  '--directory', '.e2e-server'], { stdio: 'ignore' })
let browser
let starts = 0
let complete = false
const jobId = 'a'.repeat(32)
const report = { schema_version: 'astro.report.v1', service_id: 'natal', word_count: 10000,
  sections: [{ id: 'intro', title: 'Ваши сильные стороны', text: 'Синтетический полный разбор.' },
    { id: 'last', title: 'Заключение', text: 'Последний раздел сохранён полностью.' }],
  disclaimer: 'Символическая интерпретация.' }
try {
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(base + '/mini-app/')).ok) break } catch {}
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ ...devices['iPhone 13'] })
  const page = await context.newPage()
  page.setDefaultTimeout(20000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await context.addInitScript(() => {
    window.Telegram = { WebApp: { initData: 'query_id=synthetic-astro', initDataUnsafe: {},
      ready() {}, expand() {}, onEvent() {}, offEvent() {}, openTelegramLink() {}, platform: 'ios' } }
  })
  await context.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/telegram-web-app.js'))
      return route.fulfill({ contentType: 'application/javascript', body: '// fixture' })
    if (url.pathname.includes('/mini-app/api/')) {
      let body = { ok: true }
      if (url.pathname.endsWith('/bootstrap')) body = { ok: true, telegram_id: 424242,
        first_name: 'QA', credits: 220, is_admin: true, telegram_chat_available: true,
        telegram_bot_start_required: false, bot_username: 'qa_bot', mini_app_url: base + '/mini-app/',
        image_models: [], video_models: [], recent_tasks: [], saved_references: [], actions: [],
        payment_packages: [] }
      else if (url.pathname.endsWith('/astro/places')) body = { ok: true, results: [{
        place_id: 498817, name: 'Санкт-Петербург', country_code: 'RU', timezone: 'Europe/Moscow',
        latitude: 59.9, longitude: 30.3 }] }
      else if (url.pathname.endsWith('/reports/start')) {
        starts++
        const request = route.request().postDataJSON()
        assert.equal(request.consent, true)
        assert.deepEqual(request.input, { date: '29.02.2000', time: '13:45', place_id: 498817 })
        if (starts === 1) return route.fulfill({ status: 503, contentType: 'application/json',
          body: JSON.stringify({ ok: false, error: 'temporarily_unavailable' }) })
        return route.fulfill({ status: 202, contentType: 'application/json',
          body: JSON.stringify({ ok: true, job_id: jobId, status: 'queued' }) })
      } else if (url.pathname.endsWith('/reports/status')) body = { ok: true,
        status: complete ? 'completed' : 'running', ...(complete ? { report } : {}) }
      else if (url.pathname.endsWith('/reports/history')) body = { ok: true,
        jobs: [{ job_id: jobId, service_id: 'natal', status: 'completed', created_at: 1794931200 }] }
      else if (url.pathname.endsWith('/trends/catalog')) body = { ok: true, categories: [] }
      else if (url.pathname.endsWith('/feed')) body = { ok: true, feed: [], models: [] }
      else if (url.pathname.endsWith('/genjutsu')) body = { ok: true, items: [], visible: false }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    }
    return url.origin === base ? route.continue() : route.abort()
  })
  await page.goto(base + '/mini-app/?tgWebAppData=query_id%3Dsynthetic-astro', { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: 'Астро', exact: true }).click()
  await page.getByRole('button', { name: /Натальная карта/ }).click()
  const panel = page.getByLabel('Полный персональный ИИ-разбор')
  assert.equal(starts, 0, 'Opening Astro never starts a paid generation')
  assert.doesNotMatch(await panel.innerText(), /KIE|GPT-6|провайдер|сервер|очеред/i)
  const consent = panel.getByRole('checkbox')
  assert.equal(await consent.isChecked(), false)
  const create = panel.getByRole('button', { name: 'Создать полный ИИ-разбор', exact: true })
  assert.equal(await create.isDisabled(), true)
  await page.getByLabel('person: дата рождения', { exact: true }).fill('29.02.2000')
  await page.getByLabel('person: время рождения', { exact: true }).fill('13:45')
  await page.getByRole('combobox', { name: 'person: место рождения' }).fill('Санкт')
  await page.getByRole('option', { name: /Выбрать Санкт-Петербург/ }).click()
  await consent.check()
  await create.click()
  await panel.getByText(/Сейчас не удаётся создать разбор/).waitFor()
  assert.equal(await create.isEnabled(), true, '503 leaves a deliberate retry available')
  await create.click()
  const progress = panel.getByTestId('astro-live-processing')
  await progress.getByText('Готовим ваш персональный разбор…').waitFor()
  assert.doesNotMatch(await progress.innerText(), /KIE|GPT-6|провайдер|сервер|очеред|%/i)
  assert.notEqual(await progress.locator('.astro-ai-progress-spinner').evaluate(
    element => getComputedStyle(element).animationName), 'none')
  assert.equal(starts, 2)
  complete = true
  const finished = page.getByLabel('Готовый полный ИИ-разбор')
  await finished.getByText('Последний раздел сохранён полностью.').waitFor()
  assert.equal(await progress.count(), 0)
  await panel.getByRole('button', { name: 'Мои предыдущие отчёты' }).click()
  await panel.getByRole('button', { name: 'Открыть', exact: true }).click()
  await finished.getByText('Последний раздел сохранён полностью.').waitFor()
  assert.equal(starts, 2, 'History never generates again')
  assert.deepEqual(errors, [])
  console.log('ASTRO_REPORT_MOBILE_E2E_OK consent=yes provider_copy=absent 503_recovery=yes animation=yes all_sections=yes history=yes')
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
