import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { chromium } from 'playwright'

const baseUrl = 'http://127.0.0.1:4173/mini-app/'

const bootstrapPayload = {
  ok: true,
  telegram_id: 424242,
  first_name: 'E2E',
  last_name: 'Admin',
  telegram_username: 'e2e_admin',
  photo_url: '',
  referral_code: 'E2EADMIN',
  profile_link: '',
  referral_link: '',
  channel_url: '',
  prompt_repeat_balance_rub: 0,
  prompt_repeat_total_rub: 0,
  bot_username: 'test_bot',
  // Delivery permission must not gate any Mini App generation or navigation.
  telegram_chat_available: false,
  credits: 125,
  is_admin: true,
  mini_app_url: baseUrl,
  actions: [],
  payment_packages: [
    {
      id: 'mini',
      name: 'Старт',
      credits: 25,
      price_rub: 299,
      price_stars: 299,
      lava_offer_id: 'offer-mini',
      lava_currency: 'RUB',
      robokassa_enabled: true,
      freekassa_enabled: true,
      description: 'Тестовый пакет',
    },
  ],
  image_models: [
    {
      id: 'banana_pro',
      label: 'Nano Banana Pro',
      description: 'Image model',
      cost: 2,
      ratios: ['1:1', '9:16'],
      requires_reference: false,
      max_references: 8,
      qualities: ['1K', '2K', '4K'],
      quality_costs: { '1K': 8, '2K': 12, '4K': 18 },
    },
  ],
  video_models: [
    {
      id: 'v3_pro',
      label: 'Kling 3 Pro',
      description: 'Video model',
      durations: [5, 10],
      ratios: ['16:9'],
      supports: ['text', 'imgtxt'],
      costs: { '5': 10, '10': 20 },
    },
    {
      id: 'v3_fast',
      label: 'Kling 3 Fast',
      description: 'Video model',
      durations: [5, 10],
      ratios: ['16:9'],
      supports: ['text', 'imgtxt'],
      costs: { '5': 8, '10': 16 },
    },
    {
      id: 'seedance_2_5', label: 'Seedance 2.5', description: 'Seedance references and editing',
      durations: [-1, 5, 12], ratios: ['adaptive', '16:9'], supports: ['text', 'imgtxt', 'video'],
      costs: { '-1': 20, '5': 20, '12': 48 }, quality_costs: { '480p': 3, '720p': 4 },
    },

  ],
  recent_tasks: [],
  saved_references: [],
}

const genjutsuCapability = {
  label: 'Genjutsu', resolutions: ['480p', '720p', '1080p'], min_images: 1,
  max_images: 8, max_prompt_length: 10000, minimum_video_ms: 4000,
  maximum_video_ms: 30000, roles: ['character', 'wardrobe', 'product', 'object', 'location', 'style'],
}


const notificationDefaults = JSON.parse(readFileSync(new URL('../../../bot/genjutsu/defaults.json', import.meta.url), 'utf8')).notification_templates
const durationVideo = { id: 'duration-video', kind: 'video', duration_ms: 10056, url: null }
const durationPhoto = { id: 'duration-photo', kind: 'image', url: null }
const durationAssets = new Map([[durationVideo.id, durationVideo], [durationPhoto.id, durationPhoto]])
const durationRecipe = {
  id: 'a'.repeat(32), title: 'Mobile recipe',
  source_slot: { kind: 'video', label: 'Видео-референс' },
  slots: [{ step_index: 0, reference_index: 0, role: 'character', label: 'Фото героя' }],
  user_fields: [], steps: [{ operation: 'motion_transfer', resolution: '720p' }],
  variants: 1, continuation: 'automatic', current_cost: 20,
}
let durationSequence = 0
let durationPlan = null
const durationTrims = []

const curatedTrend = {
  id: 11,
  title: 'Curated Video',
  description: 'Official trend',
  prompt_text: 'Create a cinematic motion scene',
  category: 'video',
  tags: ['trend', 'trend-video'],
  uses_count: 2,
  likes: 3,
  repeat_cost: 10,
  preview_url: 'https://cdn.example/curated.mp4',
  model: 'v3_pro',
  generation_settings: {
    kind: 'video',
    user_input: 'photo',
    model: 'v3_pro',
    scenario: 'imgtxt',
    ratio: '16:9',
    duration: 5,
    grok_mode: 'normal',
    grok_resolution: '480p',
    kling_negative_prompt: '',
    kling_cfg_scale: 0.5,
  },
  author_id: 1,
  status: 'approved',
}

const pinterestTrend = {
  id: 13,
  title: 'Повтори фото с Pinterest',
  description: 'Повтори сцену, свет и позу с Pinterest — со своей внешностью',
  prompt_text: 'Trusted Pinterest repeat prompt',
  category: 'photo',
  tags: ['trend', 'pinterest', 'pinterest-repeat', 'portrait', 'realism'],
  uses_count: 0,
  likes: 0,
  preview_url: null,
  model: 'banana_pro',
  generation_settings: {
    kind: 'image',
    user_input: 'photo',
    model: 'banana_pro',
    ratio: '9:16',
    quality: '2K',
    count: 1,
    reference_count: 2,
    reference_labels: ['РЕФЕРЕНС', 'ТЫ'],
    nsfw_checker: false,
    nsfw_enabled: false,
  },
  author_id: 1,
  status: 'approved',
}

const ordinaryPrompt = {
  id: 12,
  title: 'Ordinary Prompt',
  description: 'Must not appear in trends',
  prompt_text: 'Portrait prompt',
  category: 'photo',
  tags: ['portrait'],
  uses_count: 1,
  likes: 0,
  preview_url: 'https://cdn.example/ordinary.jpg',
  model: 'banana_pro',
  author_id: 2,
  status: 'approved',
}

async function waitForServer(url, timeoutMs = 20_000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error(`Static server did not start: ${url}`)
}

const server = spawn(
  'python3',
  ['-m', 'http.server', '4173', '--directory', '.e2e-server'],
  { stdio: 'inherit' },
)

let browser
try {
  await waitForServer(baseUrl)

  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 430, height: 900 } })
  const page = await context.newPage()
  page.setDefaultTimeout(30000)
  page.setDefaultNavigationTimeout(30000)
  page.on('pageerror', (error) => console.error('Browser page error:', error))
  page.on('console', (message) => {
    if (message.type() === 'error') console.error('Browser console error:', message.text())
  })

  let genjutsuMobileReady = false
  let seedanceGenerationPayload = null
  let copiedTrendPayload = null
  let paymentPayload = null
  let promptsPayload = null
  let trendGenerationPayload = null
  let pinterestReferencePayload = null
  let pinterestGenerationPayload = null
  const uploadQueue = []

  await page.addInitScript(() => {
    window.__copiedText = ''
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
      writeText: async (text) => { window.__copiedText = text },
    } })
    window.__openedLinks = []
    window.__telegramEventHandlers = {}
    window.Telegram = {
      WebApp: {
        initData: 'query_id=e2e',
        initDataUnsafe: {},
        ready() {},
        expand() {},
        onEvent(eventType, handler) {
          const handlers = window.__telegramEventHandlers[eventType] || []
          if (!handlers.includes(handler)) handlers.push(handler)
          window.__telegramEventHandlers[eventType] = handlers
        },
        offEvent(eventType, handler) {
          const handlers = window.__telegramEventHandlers[eventType] || []
          window.__telegramEventHandlers[eventType] = handlers.filter((item) => item !== handler)
        },
        openLink(url) {
          window.__openedLinks.push(url)
        },
        openInvoice(_url, callback) {
          callback?.('paid')
        },
      },
    }
  })

  // The production export ships a local Telegram SDK copy. Prevent that file
  // from replacing the deterministic WebApp bridge injected above.
  await page.route('**/telegram-web-app.js', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: '// Telegram WebApp is provided by the E2E init script.\n',
    })
  })

  await page.route('**/mini-app/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname

    if (path.endsWith('/genjutsu/upload')) {
      const kind = new URL(request.url()).searchParams.get('kind')
      // Upload completion is asynchronous. Keep this delay so the browser
      // fixture cannot silently depend on an instant response between inputs.
      if (kind === 'video') await new Promise(resolve => setTimeout(resolve, 150))
      const asset = { ...(kind === 'video' ? durationVideo : durationPhoto), id: `duration-upload-${++durationSequence}` }
      durationAssets.set(asset.id, asset)
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, asset }) })
      return
    }
    if (path.endsWith('/genjutsu')) {
      const requestBody = JSON.parse(request.postData() || '{}')
      if (requestBody.action === 'save_project') {
        durationPlan = requestBody.plan
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
          ok: true, project: { id: 'duration-project', revision: 1, title: requestBody.title, plan: requestBody.plan },
        }) })
        return
      }
      if (requestBody.action === 'trim') {
        durationTrims.push(requestBody)
        const asset = { ...durationVideo, id: `duration-trim-${++durationSequence}`, duration_ms: requestBody.end_ms - requestBody.start_ms }
        durationAssets.set(asset.id, asset)
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, asset }) })
        return
      }
      if (requestBody.action === 'quote' || requestBody.action === 'recipe_quote') {
        const source = durationAssets.get(requestBody.action === 'quote' ? durationPlan.source_asset_id : requestBody.source_asset_id)
        const seconds = Math.ceil(source.duration_ms / 1000)
        const quote = { id: `duration-quote-${++durationSequence}`, expires_ms: Date.now() + 300000,
          total_credits: seconds * 8, plan_hash: 'synthetic',
          allocations: [{ variant: 0, ordinal: 0, operation: 'motion_transfer', billable_seconds: seconds,
            credits_per_second: 8, reserved_credits: seconds * 8, maximum_reserve: false }] }
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
          ok: true, quote, ...(requestBody.action === 'recipe_quote' ? { recipe: durationRecipe } : {}),
        }) })
        return
      }
      if (requestBody.action === 'recipe_get') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
          ok: true, recipe: {
            id: 'a'.repeat(32), title: 'Mobile recipe',
            source_slot: { kind: 'video', label: 'Видео-референс' },
            slots: [{ step_index: 0, reference_index: 0, role: 'character', label: 'Фото героя' }],
            user_fields: [], steps: [{ operation: 'motion_transfer', resolution: '720p' }],
            variants: 1, continuation: 'automatic', current_cost: 20,
          },
        }) })
        return
      }
      const body = requestBody.action === 'availability'
        ? { ok: true, visible: true }
        : requestBody.action === 'bootstrap'
          ? {
              ok: true, catalog: {
                motion_transfer: genjutsuCapability,
                object_swap: genjutsuCapability,
                restyle: genjutsuCapability,
              },
              configured: genjutsuMobileReady, enabled: genjutsuMobileReady, is_admin: bootstrapPayload.is_admin,
              credits: bootstrapPayload.credits, provider_ready: false, media_ready: false,
              config_version: 0, limits: { max_steps: 3, max_variants: 4, poll_seconds: 5 },
              prices: {}, projects: [], runs: [], assets: genjutsuMobileReady ? [durationVideo, durationPhoto] : [],
            }
          : requestBody.action === 'settings'
            ? {
                ok: true,
                settings: {
                  admin_enabled: true, public_enabled: false, verified_operations: [],
                  prices: { motion_transfer: { '720p': null }, object_swap: { '720p': null }, restyle: { '720p': null } },
                  max_steps: 3, max_variants: 4, poll_seconds: 5,
                  notification_templates: notificationDefaults,
                },
                version: 1,
                coverage: [],
              }
            : { ok: true, items: [] }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
      return
    }

    if (path.endsWith('/prompts/link')) {
      copiedTrendPayload = JSON.parse(request.postData() || '{}')
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        ok: true, link: `https://t.me/test_bot?startapp=prompt_${curatedTrend.id}_ref_E2EADMIN`,
      }) })
      return
    }

    if (path.endsWith('/bootstrap')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(bootstrapPayload),
      })
      return
    }

    if (path.endsWith('/task-detail')) {
      const { task_id } = JSON.parse(request.postData() || '{}')
      const details = {
        'trend-e2e-task': { type: 'video', model: 'v3_pro', model_label: 'Kling 3 Pro',
          aspect_ratio: '16:9', duration: 5, cost: 10, result_url: 'https://cdn.example/trend-result.mp4' },
        'pinterest-e2e-task': { type: 'image', model: 'banana_pro', model_label: 'Nano Banana Pro',
          aspect_ratio: '9:16', duration: null, cost: 12, result_url: 'https://cdn.example/pinterest-result.jpg' },
      }[task_id]
      assert.ok(details, `Unexpected task detail request: ${task_id}`)
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        ok: true, task: { ...details, task_id, status: 'completed', created_at: '2026-10-08T00:00:00Z',
          prompt: '', prompt_preview: '', prompt_hidden: true, prompt_actions_allowed: false },
      }) })
      return
    }

    if (path.endsWith('/generate-video')) {
      seedanceGenerationPayload = JSON.parse(request.postData() || '{}')
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        ok: true, status: 'queued', task_id: 'seedance-edit-e2e', credits: 125,
        cost: 0, model_label: 'Seedance 2.5', admin_free: bootstrapPayload.is_admin,
        resolution: '720p', duration: seedanceGenerationPayload.v_duration,
        aspect_ratio: seedanceGenerationPayload.v_ratio, scenario: 'multimodal',
      }) })
      return
    }

    if (path.endsWith('/create-payment')) {
      paymentPayload = JSON.parse(request.postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          provider: paymentPayload.provider,
          order_id: 'e2e-order',
          payment_id: 'e2e-payment',
          payment_url: 'https://pay.example/e2e',
          credits: 25,
        }),
      })
      return
    }

    if (path.endsWith('/prompts')) {
      promptsPayload = JSON.parse(request.postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          prompts: [curatedTrend, pinterestTrend, ordinaryPrompt],
        }),
      })
      return
    }

    if (path.endsWith('/trends/pinterest-reference')) {
      pinterestReferencePayload = JSON.parse(request.postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          source_url: pinterestReferencePayload.url,
          image_url: 'https://i.pinimg.com/736x/e2/e2/e2/reference.jpg',
        }),
      })
      return
    }

    if (path.endsWith('/trends/pinterest-repeat/run')) {
      pinterestGenerationPayload = JSON.parse(request.postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          status: 'done',
          task_id: 'pinterest-e2e-task',
          saved_url: 'https://cdn.example/pinterest-result.jpg',
          task_type: 'image',
          credits: 103,
          cost: 12,
          model: 'banana_pro',
          model_label: 'Nano Banana Pro',
          aspect_ratio: '9:16',
          duration: null,
          prompt_hidden: true,
          prompt_actions_allowed: false,
          trend_id: pinterestTrend.id,
        }),
      })
      return
    }

    if (path.endsWith('/trends/run')) {
      trendGenerationPayload = JSON.parse(request.postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          status: 'done',
          task_id: 'trend-e2e-task',
          saved_url: 'https://cdn.example/trend-result.mp4',
          task_type: 'video',
          credits: 115,
          cost: 10,
          model: 'v3_pro',
          model_label: 'Kling 3 Pro',
          aspect_ratio: '16:9',
          duration: 5,
          prompt_hidden: true,
          prompt_actions_allowed: false,
          trend_id: curatedTrend.id,
        }),
      })
      return
    }

    if (path.endsWith('/upload')) {
      const queuedUpload = uploadQueue.shift() || {
        url: 'https://cdn.example/trend-upload.mp4',
        kind: 'video',
        filename: 'trend.mp4',
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          url: queuedUpload.url,
          kind: queuedUpload.kind,
          filename: queuedUpload.filename,
          reference: null,
        }),
      })
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    })
  })

  await page.goto(`${baseUrl}?tgWebAppData=query_id%3De2e`, {
    waitUntil: 'networkidle',
  })
  await page.getByText('Онлайн', { exact: true }).waitFor()
  assert.equal(await page.getByText('Разреши боту писать тебе', { exact: true }).count(), 0)

  // Default landing E2E: a normal Mini App launch opens Trends before any nav click.
  // Pinterest AI is excluded from the showcase; it is reachable via Services only.
  await page.getByText('Curated Video', { exact: true }).waitFor()
  assert.equal(await page.getByText('Повтори фото с Pinterest', { exact: true }).count(), 0)
  assert.equal(promptsPayload?.source, 'tag')
  assert.equal(promptsPayload?.tag, 'trend')
  assert.equal(await page.getByText('Ordinary Prompt', { exact: true }).count(), 0)

  // Copy the server-owned personal link unchanged, including template and referrer.
  await page.getByRole('button', { name: 'Ссылка', exact: true }).first().click()
  await page.getByRole('button', { name: 'Скопировано', exact: true }).waitFor()
  assert.equal(copiedTrendPayload?.prompt_id, curatedTrend.id)
  assert.equal(copiedTrendPayload?.referral_code, undefined)
  assert.equal(await page.evaluate(() => window.__copiedText),
    `https://t.me/test_bot?startapp=prompt_${curatedTrend.id}_ref_E2EADMIN`)

  // Returning from a bot Start link must not reset an in-progress form.
  // Trends remains the first-launch default; later navigation is explicit.
  await page.getByRole('button', { name: 'Фото', exact: true }).click()
  const returnDraft = page.getByPlaceholder('Опишите сцену, стиль, свет, камеру, детали персонажей и желаемый результат...')
  await returnDraft.fill('Keep this draft when Telegram activates the WebView')
  await page.evaluate(() => {
    for (const handler of window.__telegramEventHandlers?.activated || []) handler()
  })
  assert.equal(await returnDraft.inputValue(), 'Keep this draft when Telegram activates the WebView')
  assert.equal(await page.getByText('Curated Video', { exact: true }).count(), 0)
  await page.getByRole('button', { name: 'Тренды', exact: true }).click()
  await page.getByText('Curated Video', { exact: true }).waitFor()

  // Payment E2E: Robokassa is primary, KASSA is reserve, Lava stays lower.
  await page.locator('header button').last().click()

  await page.getByRole('button', { name: 'СБП / карта', exact: true }).click()
  await page.waitForFunction(() => (
    Array.isArray(window.__openedLinks)
      && window.__openedLinks.length >= 1
      && window.__openedLinks[0] === 'https://pay.example/e2e'
  ))
  assert.equal(paymentPayload?.provider, 'robokassa')
  assert.equal(paymentPayload?.customer_email, '')

  await page.getByRole('button', { name: 'Картой', exact: true }).click()
  await page.waitForFunction(() => (
    Array.isArray(window.__openedLinks)
      && window.__openedLinks.length >= 2
      && window.__openedLinks[1] === 'https://pay.example/e2e'
  ))
  assert.equal(paymentPayload?.provider, 'freekassa_card')
  assert.equal(paymentPayload?.customer_email, '')

  await page.getByLabel('Почта для дополнительной оплаты через Lava').fill('Buyer2026@Mail.ru')
  const lavaCardButton = page
    .getByText('Lava · дополнительный способ', { exact: true })
    .locator('xpath=following-sibling::button[1]')
  await lavaCardButton.click()
  await page.waitForFunction(() => (
    Array.isArray(window.__openedLinks)
      && window.__openedLinks.length >= 3
      && window.__openedLinks[2] === 'https://pay.example/e2e'
  ))
  assert.equal(paymentPayload?.provider, 'lava_card')
  assert.equal(paymentPayload?.customer_email, 'buyer2026@mail.ru')
  await page.getByRole('button', { name: 'Закрыть пополнение' }).click()

  // Trends E2E: server-side tag query + client-side filtering.
  await page.getByRole('button', { name: /Тренды/ }).click()
  await page.getByText('Curated Video', { exact: true }).waitFor()
  assert.equal(await page.getByText('Повтори фото с Pinterest', { exact: true }).count(), 0)
  assert.equal(promptsPayload?.source, 'tag')
  assert.equal(promptsPayload?.tag, 'trend')
  assert.equal(await page.getByText('Ordinary Prompt', { exact: true }).count(), 0)

  // Generic user trend E2E: uploading alone must NOT start generation anymore.
  const curatedCard = page.locator('article').filter({ hasText: curatedTrend.title })
  await curatedCard.getByRole('button', { name: 'Повторить · 10🍌', exact: true }).click()
  const trendRunner = page.getByRole('dialog')
  await trendRunner.getByText('Загрузите свои фото', { exact: true }).waitFor()
  assert.equal(await trendRunner.locator('select').count(), 0)
  assert.equal(await trendRunner.getByText('Модель', { exact: true }).count(), 0)
  assert.equal(await trendRunner.getByText('Формат', { exact: true }).count(), 0)
  assert.equal(await trendRunner.getByText('Длительность', { exact: true }).count(), 0)

  uploadQueue.push({
    url: 'https://cdn.example/user-trend-photo.jpg',
    kind: 'image',
    filename: 'user-photo.jpg',
  })
  await trendRunner.locator('input[type="file"]').setInputFiles({
    name: 'user-photo.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from([255, 216, 255, 224, 0, 16, 74, 70, 73, 70]),
  })
  await trendRunner.getByText('Сгенерировать · 10🍌', { exact: true }).waitFor()
  await page.waitForTimeout(100)
  assert.equal(trendGenerationPayload, null, 'Uploading a trend reference must not auto-run')

  const generatedResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith('/trends/run'),
  )
  await trendRunner.getByRole('button', { name: 'Сгенерировать · 10🍌', exact: true }).click()
  await generatedResponse

  assert.equal(trendGenerationPayload?.trend_id, curatedTrend.id)
  assert.deepEqual(
    trendGenerationPayload?.reference_urls,
    ['https://cdn.example/user-trend-photo.jpg'],
  )
  for (const forbiddenField of [
    'model',
    'prompt',
    'ratio',
    'quality',
    'duration',
    'generation_settings',
  ]) {
    assert.equal(
      Object.hasOwn(trendGenerationPayload || {}, forbiddenField),
      false,
      `User trend request must not contain ${forbiddenField}`,
    )
  }

  const taskDetailTitle = page.getByText('Детали задачи', { exact: true })
  // The task drawer can enter while the runner's exiting overlay still captures clicks.
  await trendRunner.waitFor({ state: 'hidden' })
  await page.locator('[data-slot="dialog-overlay"]').waitFor({ state: 'detached' })
  await taskDetailTitle.waitFor()
  await page.mouse.click(10, 10)
  await taskDetailTitle.waitFor({ state: 'hidden' })

  // Pinterest repeat E2E: entry only via Services -> Pinterest AI tile,
  // then Pinterest URL -> identity photo -> measurements -> explicit Create.
  await page.getByRole('button', { name: /Сервисы/ }).click()
  const pinterestTile = page.getByRole('button', { name: /Pinterest AI/ })
  await pinterestTile.waitFor()
  await pinterestTile.click()
  const pinterestRunner = page.getByRole('dialog')
  await pinterestRunner.getByText('Повтори фото с Pinterest', { exact: true }).waitFor()
  await pinterestRunner.getByText('РЕФЕРЕНС', { exact: true }).waitFor()
  await pinterestRunner.getByText('ТЫ', { exact: true }).waitFor()
  const seedreamPinterestModel = pinterestRunner.getByRole('button', { name: 'Seedream 5 Pro', exact: true })
  await seedreamPinterestModel.waitFor()
  await seedreamPinterestModel.click()

  const pinterestFileInputs = pinterestRunner.locator('input[type="file"]')
  assert.equal(await pinterestFileInputs.count(), 2)
  const createButton = pinterestRunner.getByRole('button', { name: 'Создать →', exact: true })
  assert.equal(await createButton.isDisabled(), true)

  uploadQueue.push({
    url: 'https://cdn.example/pinterest-reference.jpg',
    kind: 'image',
    filename: 'pinterest-reference.jpg',
  })
  await pinterestFileInputs.nth(0).setInputFiles({
    name: 'pinterest-reference.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from([255, 216, 255, 224, 0, 16, 74, 70, 73, 70]),
  })

  assert.equal(await createButton.isDisabled(), true, 'One reference must not be enough to generate')
  assert.equal(pinterestGenerationPayload, null)

  uploadQueue.push({
    url: 'https://cdn.example/pinterest-user.jpg',
    kind: 'image',
    filename: 'pinterest-user.jpg',
  })
  await pinterestFileInputs.nth(1).setInputFiles({
    name: 'pinterest-user.jpg',
    mimeType: 'image/jpeg',
    buffer: Buffer.from([255, 216, 255, 224, 0, 16, 74, 70, 73, 70]),
  })

  const heightInput = pinterestRunner.locator('label').filter({ hasText: 'Рост' }).locator('input')
  const weightInput = pinterestRunner.locator('label').filter({ hasText: 'Вес' }).locator('input')
  await heightInput.fill('172')
  await weightInput.fill('64')

  await pinterestRunner.getByText('Источник', { exact: true }).waitFor()
  assert.equal(await createButton.isDisabled(), false)
  assert.equal(pinterestGenerationPayload, null, 'Two references must still require explicit Create')

  const pinterestRunResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith('/trends/pinterest-repeat/run'),
  )
  await createButton.click()
  await pinterestRunResponse

  assert.equal(pinterestGenerationPayload?.trend_id, pinterestTrend.id)
  assert.deepEqual(pinterestGenerationPayload?.reference_urls, [
    'https://cdn.example/pinterest-reference.jpg',
    'https://cdn.example/pinterest-user.jpg',
  ])
  assert.equal(pinterestGenerationPayload?.height_cm, 172)
  assert.equal(pinterestGenerationPayload?.weight_kg, 64)
  assert.equal(pinterestGenerationPayload?.model, 'seedream_5_pro')
  for (const forbiddenField of [
    'prompt',
    'ratio',
    'quality',
    'count',
    'generation_settings',
  ]) {
    assert.equal(
      Object.hasOwn(pinterestGenerationPayload || {}, forbiddenField),
      false,
      `Pinterest request must not allow client override of ${forbiddenField}`,
    )
  }

  await pinterestRunner.waitFor({ state: 'hidden' })
  await page.locator('[data-slot="dialog-overlay"]').waitFor({ state: 'detached' })
  await taskDetailTitle.waitFor()
  await page.mouse.click(10, 10)
  await taskDetailTitle.waitFor({ state: 'hidden' })

  // Admin upload E2E: uploaded preview survives duration/model changes.
  await page.getByRole('button', { name: /Тренды/ }).click()
  await page.getByRole('button', { name: 'Добавить', exact: true }).click()
  await page.getByRole('button', { name: 'Видео-тренд', exact: true }).click()
  const createTrendForm = page.locator('section').filter({ hasText: 'Новый тренд' })
  await createTrendForm.getByRole('button', { name: 'Промо-видео', exact: true }).click()
  uploadQueue.push({
    url: 'https://cdn.example/trend-upload.mp4',
    kind: 'video',
    filename: 'trend.mp4',
  })
  await createTrendForm.locator('input[type="file"]').setInputFiles({
    name: 'trend.mp4',
    mimeType: 'video/mp4',
    buffer: Buffer.from([0, 0, 0, 24, 102, 116, 121, 112]),
  })

  const uploadedPreview = page.locator('video[src="https://cdn.example/trend-upload.mp4"]')
  await uploadedPreview.waitFor()

  await page.locator('label').filter({ hasText: 'Длительность' }).locator('select').selectOption('10')
  assert.equal(await uploadedPreview.count(), 1)

  await page.locator('label').filter({ hasText: 'Видео-нейросеть' }).locator('select').selectOption('v3_fast')
  assert.equal(await uploadedPreview.count(), 1)

  // Exercise the exported Seedance UI with mocked provider transport only.
  for (const editing of [true, false]) {
    bootstrapPayload.is_admin = editing
    await page.goto(`${baseUrl}?tgWebAppData=query_id%3De2e`, { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: 'Видео', exact: true }).click()
    const durationSlider = page.getByLabel('Длительность видео', { exact: true })
    await durationSlider.waitFor()
    await durationSlider.focus()
    await durationSlider.press('Home')
    for (let second = 4; second < 12; second += 1) await durationSlider.press('ArrowRight')
    await page.getByRole('button', { name: '16:9', exact: true }).click()
    await page.getByText('Для продвинутых: добавить URL или Asset ID', { exact: true }).click()
    await page.getByLabel('Видео — по одному URL / asset:// на строку', { exact: true }).fill('https://cdn.example/source.mp4')
    await page.getByLabel('Промпт для Seedance 2.5', { exact: true }).fill('Replace the background in this video')
    if (editing) {
      await page.getByLabel('Редактировать видео', { exact: true }).check()
      assert.equal(await durationSlider.isDisabled(), true)
      assert.equal(await page.getByRole('button', { name: '16:9', exact: true }).isDisabled(), true)
      await page.getByText(/Одно исходное видео, 4–30 секунд/).waitFor()
      // Toggling off restores remembered generation parameters.
      await page.getByLabel('Редактировать видео', { exact: true }).uncheck()
      assert.equal(await durationSlider.inputValue(), '12')
      assert.equal(await durationSlider.isEnabled(), true)
      await page.getByLabel('Редактировать видео', { exact: true }).check()
    } else {
      assert.equal(await page.getByLabel('Редактировать видео', { exact: true }).count(), 0)
      assert.equal(await durationSlider.isEnabled(), true)
    }
    const generationRequest = page.waitForResponse((response) => response.url().endsWith('/generate-video') && response.status() === 200)
    await page.getByRole('button', { name: /Создать видео/ }).click()
    await generationRequest
    assert.equal(seedanceGenerationPayload.seedance25_video_editing, editing)
    assert.equal(seedanceGenerationPayload.v_duration, editing ? -1 : 12)
    assert.equal(seedanceGenerationPayload.v_ratio, editing ? 'adaptive' : '16:9')
    assert.deepEqual(seedanceGenerationPayload.v_reference_videos, ['https://cdn.example/source.mp4'])
  }

  // Genjutsu is reachable from the shared product shell and loads its real lazy UI.
  await page.getByRole('button', { name: 'Студия', exact: true }).click()
  await page.getByRole('button', { name: /Higgsfield Genjutsu/ }).click()
  const genjutsuRegion = page.getByRole('region', { name: 'Студия Genjutsu' })
  await genjutsuRegion.waitFor()
  await page.getByText('Интеграция ещё не настроена.', { exact: false }).waitFor()
  const genjutsuDialog = page.getByRole('dialog')
  const dialogBox = await genjutsuDialog.boundingBox()
  assert.ok(dialogBox, 'Genjutsu dialog must be visible')
  assert.ok(dialogBox.x <= 1, `mobile dialog must start at viewport edge, got x=${dialogBox.x}`)
  assert.ok(dialogBox.width >= 429, `mobile dialog must fill 430px viewport, got width=${dialogBox.width}`)
  assert.equal(
    await genjutsuRegion.evaluate((element) => element.scrollWidth <= element.clientWidth),
    true,
    'Genjutsu region must not scroll horizontally on mobile',
  )
  const operationGrid = genjutsuRegion.locator('[data-testid="genjutsu-operation-grid"]')
  await operationGrid.waitFor()
  assert.equal(
    await operationGrid.evaluate((element) => element.scrollWidth <= element.clientWidth),
    true,
    'Genjutsu operation chooser must fit without horizontal scrolling',
  )
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    true,
    'Genjutsu must not widen the Telegram viewport',
  )
  await page.getByRole('button', { name: 'Закрыть студию' }).click()

  // Admin launch opens Genjutsu directly on management in the real lazy UI.
  bootstrapPayload.is_admin = true
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('genjutsu:open', { detail: { admin: true } })))
  await page.getByRole('region', { name: 'Студия Genjutsu' }).waitFor()
  await page.getByText(/Управление доступом и тарифами/).waitFor()
  await page.getByRole('button', { name: 'Закрыть студию' }).click()


  // Exercise the actual editor and recipe upload surface at narrow phone widths.
  genjutsuMobileReady = true
  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 820 })
    for (const recipeMode of [false, true]) {
      await page.evaluate((recipe) => window.dispatchEvent(new CustomEvent('genjutsu:open', {
        detail: recipe ? { recipe_id: 'a'.repeat(32) } : {},
      })), recipeMode)
      const region = page.getByRole('region', { name: 'Студия Genjutsu' })
      await region.waitFor()
      await (recipeMode
        ? page.getByText('Референсы тренда', { exact: true })
        : page.getByTestId('genjutsu-operation-grid')).waitFor()
      // Wait for the open animation to finish before measuring the viewport.
      await page.waitForFunction(() => {
        const dialog = document.querySelector('[role="dialog"]')
        if (!dialog) return false
        const rect = dialog.getBoundingClientRect()
        return Math.abs(rect.x) < 0.1 && Math.abs(rect.width - innerWidth) < 0.1
          && getComputedStyle(dialog).opacity === '1'
      })
      assert.equal(await region.evaluate(el => el.scrollWidth <= el.clientWidth), true,
        `Genjutsu ${recipeMode ? 'recipe' : 'editor'} must fit ${width}px`)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      assert.equal(await region.evaluate(el => getComputedStyle(el).overflowY), 'visible',
        'The dialog must own vertical scrolling')
      const outsideControls = await region.evaluate(el => [...el.querySelectorAll('fieldset,label,button,select')].filter(child => {
        const box = child.getBoundingClientRect()
        return !child.closest('.sr-only') && box.width > 0 && (box.left < -1 || box.right > innerWidth + 1)
      }).map(child => ({ tag: child.tagName, className: child.className, text: child.textContent?.slice(0, 80) })))
      assert.deepEqual(outsideControls, [], `Visible form controls must stay inside ${width}px`)
      const headerOverlap = await region.locator('header').evaluate(header => {
        const close = header.querySelector('button').getBoundingClientRect()
        return [...header.querySelector('div > div').children].some(el => {
          const box = el.getBoundingClientRect()
          return box.right > close.left && box.left < close.right
            && box.bottom > close.top && box.top < close.bottom
        })
      })
      assert.equal(headerOverlap, false, `Genjutsu title must not overlap Close at ${width}px`)
      if (recipeMode) {
        const video = page.getByLabel('Видео-референс', { exact: true })
        const photo = page.getByLabel('Фото героя', { exact: true })
        assert.match(await video.getAttribute('accept'), /video\//)
        assert.match(await photo.getAttribute('accept'), /image\//)
        assert.equal(await video.isEnabled(), true)
        assert.equal(await photo.isEnabled(), true)
        for (const input of [video, photo]) {
          const chooseFile = page.waitForEvent('filechooser')
          await input.locator('..').click()
          await (await chooseFile).setFiles([])
        }
        assert.equal(await region.evaluate(el => {
          const inputs = [...el.querySelectorAll('input[type="file"]')]
          return inputs.length === 2 && inputs[0].closest('fieldset') === inputs[1].closest('fieldset')
        }), true, 'Trend photo and video inputs must share one surface')
      } else {
        const videoInput = region.locator('input[type="file"][accept*="video"]').first()
        const chooseFile = page.waitForEvent('filechooser')
        await videoInput.locator('..').click()
        await (await chooseFile).setFiles([])
        await page.getByRole('dialog').evaluate(el => { el.scrollTop = 250 })
        const button = await page.getByRole('button', { name: 'Рассчитать стоимость', exact: true }).boundingBox()
        assert.ok(button && 820 - (button.y + button.height) >= 0
          && 820 - (button.y + button.height) <= 48,
        `Genjutsu sticky action must use the dialog viewport at ${width}px`)
      }
      if (process.env.GENJUTSU_QA_SCREENSHOTS) {
        await page.screenshot({ path: `${process.env.GENJUTSU_QA_SCREENSHOTS}/genjutsu-${width}-${recipeMode ? 'recipe' : 'editor'}.png` })
      }
      await page.getByRole('button', { name: 'Закрыть студию' }).click()
      await page.getByRole('dialog').waitFor({ state: 'hidden' })
    }
  }


  // The default range uses actual uploaded metadata, not the old hidden 5 seconds.
  bootstrapPayload.is_admin = false
  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 820 })
    for (const recipeMode of [false, true]) {
      await page.evaluate(recipe => window.dispatchEvent(new CustomEvent('genjutsu:open', {
        detail: recipe ? { recipe_id: 'a'.repeat(32) } : {},
      })), recipeMode)
      if (recipeMode) {
        await page.getByLabel('Видео-референс', { exact: true }).setInputFiles({
          name: 'synthetic.mp4', mimeType: 'video/mp4', buffer: Buffer.from('mocked video'),
        })
        // setInputFiles does not wait for a disabled fieldset. Wait for the
        // first action to finish before submitting the second reference.
        await page.getByText('Видео загружено — нажмите, чтобы заменить', { exact: true }).waitFor()
        await page.getByLabel('Фото героя', { exact: true }).setInputFiles({
          name: 'synthetic.png', mimeType: 'image/png', buffer: Buffer.from('mocked image'),
        })
        await page.getByText('Фото загружено — нажмите, чтобы заменить', { exact: true }).waitFor()
      } else {
        await page.getByLabel('Видео из библиотеки').selectOption(durationVideo.id)
        await page.getByLabel('Добавить референс к шагу 1').selectOption(durationPhoto.id)
      }
      const begin = page.getByLabel('Начало, сек.', { exact: true })
      const end = page.getByLabel('Конец, сек.', { exact: true })
      await end.waitFor()
      assert.equal(await begin.inputValue(), '0')
      assert.equal(await end.inputValue(), '10.056')
      assert.equal(await begin.evaluate(el => Boolean(el.closest('details'))), false)
      assert.equal(await page.getByText('Выбрать фрагмент', { exact: true }).count(), 0)
      const trimCount = durationTrims.length
      await page.getByRole('button', { name: 'Рассчитать стоимость', exact: true }).click()
      await page.getByText('88 бананов', { exact: true }).waitFor()
      assert.equal(durationTrims.length, trimCount, 'Whole video must not be silently trimmed')
      await page.getByText('Длительность видео к запуску: 10.056 с', { exact: true }).waitFor()
      assert.ok((await page.getByRole('region', { name: 'Студия Genjutsu' }).innerText()).includes('11 с к оплате'))
      await begin.scrollIntoViewIfNeeded()
      if (process.env.GENJUTSU_QA_SCREENSHOTS) await page.screenshot({
        path: `${process.env.GENJUTSU_QA_SCREENSHOTS}/duration-full-${width}-${recipeMode ? 'recipe' : 'editor'}.png`,
      })
      await end.fill('5')
      await page.getByRole('button', { name: recipeMode ? 'Запустить тренд' : 'Запустить', exact: true }).waitFor({ state: 'hidden' })
      assert.equal(await page.getByRole('button', { name: 'Рассчитать стоимость', exact: true }).isDisabled(), true)
      await page.getByRole('button', { name: 'Применить фрагмент', exact: true }).click()
      await page.getByText('Фрагмент подготовлен: 5 с. Рассчитайте стоимость.', { exact: true }).waitFor()
      assert.equal(await begin.inputValue(), '0')
      assert.equal(await end.inputValue(), '5')
      assert.equal(durationTrims.length, trimCount + 1)
      assert.equal(durationTrims.at(-1).start_ms, 0)
      assert.equal(durationTrims.at(-1).end_ms, 5000)
      await page.getByRole('button', { name: 'Рассчитать стоимость', exact: true }).click()
      await page.getByText('40 бананов', { exact: true }).waitFor()
      const region = page.getByRole('region', { name: 'Студия Genjutsu' })
      assert.equal(await region.evaluate(el => el.scrollWidth <= el.clientWidth), true)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      await begin.scrollIntoViewIfNeeded()
      if (process.env.GENJUTSU_QA_SCREENSHOTS) await page.screenshot({
        path: `${process.env.GENJUTSU_QA_SCREENSHOTS}/duration-${width}-${recipeMode ? 'recipe' : 'editor'}.png`,
      })
      await page.getByRole('button', { name: 'Закрыть студию' }).click()
      await page.getByRole('dialog').waitFor({ state: 'hidden' })
    }
  }

  bootstrapPayload.is_admin = true
  await page.setViewportSize({ width: 320, height: 820 })
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('genjutsu:open', { detail: { admin: true } })))
  const templates = page.getByText('Тексты уведомлений', { exact: true })
  await templates.click()
  await page.getByLabel('Возврат на баланс', { exact: true }).waitFor()
  const adminRegion = page.getByRole('region', { name: 'Студия Genjutsu' })
  assert.equal(await adminRegion.evaluate(el => el.scrollWidth <= el.clientWidth), true)
  const clippedTemplates = await adminRegion.locator('textarea').evaluateAll(elements => elements.filter(el => {
    const rect = el.getBoundingClientRect()
    return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1)
  }).length)
  assert.equal(clippedTemplates, 0, 'Notification templates must fit 320px')
  await page.getByLabel('Возврат на баланс', { exact: true }).scrollIntoViewIfNeeded()
  if (process.env.GENJUTSU_QA_SCREENSHOTS) await page.screenshot({
    path: `${process.env.GENJUTSU_QA_SCREENSHOTS}/notification-admin-320.png`,
  })
  await page.getByRole('button', { name: 'Закрыть студию' }).click()
  await page.getByRole('dialog').waitFor({ state: 'hidden' })

  console.log('Mini App critical browser E2E passed')
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}

// Include owner reference-consent regression in the existing CI browser gate.
await import('./private-repeat-permission.mjs')

// Ordinary Genjutsu output publication and private recipe repeats stay offline.
await import('./genjutsu-feed-bridge.mjs')

// Generic Seedance admin upload and reference privacy stay in the browser gate.
await import('./seedance-trend-upload.mjs')

// Explicit identity-transfer pricing, reference roles, and ordinary mode regression.
await import('./seedance25-identity-transfer.mjs')
