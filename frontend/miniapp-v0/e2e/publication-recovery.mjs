import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { chromium } from 'playwright'

const port = Number(process.env.PUBLICATION_RECOVERY_E2E_PORT || 4197)
const origin = 'http://127.0.0.1:' + port
const base = origin + '/mini-app/'
const root = mkdtempSync(join(tmpdir(), 'publication-recovery-browser-'))
symlinkSync(resolve('out'), join(root, 'mini-app'), 'dir')
const server = spawn('python3', ['-m', 'http.server', String(port), '--bind', '127.0.0.1', '--directory', root], { stdio: 'ignore' })
const bootstrap = {
  ok: true, telegram_id: 82211, first_name: 'Owner', telegram_username: 'owner',
  photo_url: '', referral_code: 'OWNER', profile_link: '', referral_link: '', channel_url: '',
  bot_username: 'test_bot', telegram_chat_available: true, telegram_bot_start_required: false,
  credits: 500, is_admin: false, mini_app_url: base, actions: [], payment_packages: [],
  image_models: [], video_models: [], recent_tasks: [], saved_references: [],
}
const cases = [
  { key: 'bot-published-photo', kind: 'image', published: true, private: false, width: 390 },
  { key: 'private-video-remix', kind: 'video', published: false, private: true, width: 320 },
  { key: 'private-trend-photo', kind: 'image', published: true, private: true, width: 430 },
]
let browser
try {
  const deadline = Date.now() + 18000
  while (true) {
    try { if ((await fetch(base)).ok) break } catch {}
    if (Date.now() > deadline) throw new Error('Static Mini App export unavailable')
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  browser = await chromium.launch({ headless: true })
  for (const scenario of cases) {
    const context = await browser.newContext({ viewport: { width: scenario.width, height: 880 }, serviceWorkers: 'block' })
    const page = await context.newPage()
    page.setDefaultTimeout(13000)
    const requests = [], mutations = [], exceptions = [], unknown = []
    page.on('pageerror', error => exceptions.push(error.message))
    page.on('dialog', dialog => dialog.accept())
    await page.addInitScript(() => {
      window.Telegram = { WebApp: { initData: 'query_id=publication-fixture', initDataUnsafe: {},
        ready() {}, expand() {}, onEvent() {}, offEvent() {} } }
    })
    const task = {
      task_id: scenario.key, type: scenario.kind, model: scenario.kind === 'image' ? 'banana_pro' : 'seedance_2_5',
      model_label: 'Fixture', aspect_ratio: '1:1', status: 'completed',
      result_url: 'https://example.test/' + scenario.key + (scenario.kind === 'image' ? '.png' : '.mp4'),
      prompt: scenario.private ? '' : 'My owned prompt', prompt_preview: scenario.private ? '' : 'My owned prompt',
      created_at: '2026-10-14T00:00:00Z', cost: 10,
      prompt_hidden: scenario.private, prompt_actions_allowed: !scenario.private,
      is_public_feed: scenario.published, is_profile_visible: scenario.published,
      publication_scope: scenario.published ? 'feed' : 'private',
      feed_prompt_visible: !scenario.private && scenario.published,
      publication_reference_images: scenario.private ? [] : ['https://example.test/owned.png'],
      publication_reference_image_indices: scenario.private ? [] : [0],
      publication_reference_videos: [], publication_reference_video_indices: [],
    }
    await page.route('**/*', async route => {
      const req = route.request(), target = new URL(req.url())
      if (target.pathname.endsWith('/telegram-web-app.js')) {
        return route.fulfill({ contentType: 'application/javascript', body: '// fixture' })
      }
      if (target.hostname === 'example.test') {
        return route.fulfill({ status: 200, contentType: scenario.kind === 'image' ? 'image/svg+xml' : 'video/mp4',
          body: scenario.kind === 'image' ? '<svg xmlns="http://www.w3.org/2000/svg"><rect width="2" height="2"/></svg>' : '' })
      }
      if (target.pathname.includes('/mini-app/api/')) {
        const path = target.pathname.split('/api/')[1]
        const payload = JSON.parse(req.postData() || '{}')
        requests.push({ path, payload })
        let response = { ok: true }
        if (path === 'bootstrap') response = { ...bootstrap, recent_tasks: [task] }
        else if (path === 'task-detail') {
          assert.equal(payload.task_id, scenario.key)
          response = { ok: true, task }
        } else if (path === 'generations/share') {
          mutations.push(payload)
          assert.equal(payload.task_id, scenario.key)
          if (payload.publication_scope === 'private') response = { ok: true, removed: true }
          else response = { ok: true, feed_item: {
            id: 312, task_id: scenario.key, model: task.model, gen_type: scenario.kind,
            result_url: task.result_url, result_urls: [task.result_url],
            prompt: scenario.private ? '' : task.prompt, prompt_hidden: scenario.private,
            prompt_actions_allowed: !scenario.private,
            reference_images: [], reference_videos: [],
            publication_scope: payload.publication_scope, is_profile_visible: true,
            is_public_feed: payload.publication_scope === 'feed',
            feed_interactions_enabled: payload.publication_scope === 'feed',
            feed_prompt_visible: payload.prompt_visible, feed_references_visible: payload.references_visible,
            feed_blurred: payload.feed_blurred, author: 'Owner', author_referral_code: 'OWNER', is_mine: true,
            likes_count: 0, shares_count: 0, remixes: 0, score: 0,
            aspect_ratio: task.aspect_ratio, created_at: task.created_at,
            publication_link: 'https://t.me/test_bot?startapp=feed_312',
          } }
        } else if (path === 'feed' || path === 'feed/my') response = { ok: true, feed: [], models: [] }
        else if (path === 'prompts') response = { ok: true, prompts: [] }
        else if (path === 'genjutsu') response = { ok: true, visible: false }
        else if (path === 'client-log') response = { ok: true }
        else { unknown.push(path); response = { ok: false, error: 'Unexpected synthetic request' } }
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response) })
      }
      if (target.origin === origin) return route.continue()
      unknown.push(target.toString())
      return route.abort()
    })
    await page.goto(base + '?startapp=task_' + scenario.key)
    await page.getByRole('heading', { name: 'Детали задачи' }).waitFor()
    await page.getByRole('button', { name: scenario.published ? 'Настроить публикацию' : 'Опубликовать', exact: true }).click()
    await page.getByText('Куда опубликовать?').waitFor()
    if (scenario.private) {
      await page.getByText(/Промпт и исходные референсы чужого повтора/).waitFor()
      assert.equal(await page.getByRole('button', { name: 'Prompt', exact: true }).count(), 0)
      assert.equal(await page.getByRole('group', { name: 'Референсы для повторов' }).count(), 0)
    }
    await page.getByRole('button', { name: 'Только профиль', exact: true }).click()
    await page.getByRole('button', { name: 'Blur', exact: true }).click()
    await page.getByRole('button', { name: scenario.published ? 'Сохранить публикацию' : 'Опубликовать', exact: true }).first().click()
    try {
      await page.getByRole('button', { name: 'Скопировать', exact: true }).last().waitFor()
    } catch (error) {
      console.error('DEBUG RECOVERY', scenario.key, JSON.stringify({ mutations, exceptions, unknown }))
      console.error((await page.locator('body').innerText()).slice(-2600))
      throw error
    }
    assert.equal(mutations.length, 1, 'One explicit settings write, not a new generation')
    const data = mutations[0]
    assert.equal(data.publication_scope, 'profile')
    assert.equal(data.feed_blurred, true)
    if (scenario.private) {
      assert.equal(data.prompt_visible, false)
      assert.equal(data.references_visible, false)
      assert.deepEqual(data.reference_image_indices, [])
      assert.deepEqual(data.reference_video_indices, [])
      assert.deepEqual(data.repeat_reference_image_indices, [])
    }
    assert.equal(requests.filter(x => x.path.startsWith('generate')).length, 0)
    assert.deepEqual(exceptions, [], 'No runtime errors from the own-publication editor')
    assert.deepEqual(unknown, [], 'No unmocked external requests')
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'No horizontal overflow')
    console.log('PASS ' + scenario.key + ' ' + scenario.width + 'px: bot/remix/trend own settings, private recipe and published link')
    await context.close()
  }
} finally {
  await browser?.close()
  server.kill('SIGTERM')
  rmSync(root, { recursive: true, force: true })
}
