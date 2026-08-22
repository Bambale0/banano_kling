import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
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
  ],
  recent_tasks: [],
  saved_references: [],
}

const curatedTrend = {
  id: 11,
  title: 'Curated Video',
  description: 'Official trend',
  prompt_text: 'Create a cinematic motion scene',
  category: 'video',
  tags: ['trend', 'trend-video'],
  uses_count: 2,
  likes: 3,
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

  let paymentPayload = null
  let promptsPayload = null
  let trendGenerationPayload = null
  let pinterestReferencePayload = null
  let pinterestGenerationPayload = null
  const uploadQueue = []

  await page.addInitScript(() => {
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

    if (path.endsWith('/bootstrap')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(bootstrapPayload),
      })
      return
    }

    if (path.endsWith('/create-payment')) {
      paymentPayload = JSON.parse(request.postData() || '{}')
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          provider: 'lava',
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

  // Default landing E2E: a normal Mini App launch opens Trends before any nav click.
  await page.getByText('Curated Video', { exact: true }).waitFor()
  await page.getByText('Повтори фото с Pinterest', { exact: true }).waitFor()
  assert.equal(promptsPayload?.source, 'tag')
  assert.equal(promptsPayload?.tag, 'trend')
  assert.equal(await page.getByText('Ordinary Prompt', { exact: true }).count(), 0)

  // Telegram can keep the WebView alive between openings. Re-activation must
  // restore the product default for sessions without an actionable deep link.
  await page.getByRole('button', { name: 'Фото', exact: true }).click()
  await page.getByText('Curated Video', { exact: true }).waitFor({ state: 'hidden' })
  await page.evaluate(() => {
    for (const handler of window.__telegramEventHandlers?.activated || []) handler()
  })
  await page.getByText('Curated Video', { exact: true }).waitFor()

  // Payment E2E: form email -> backend payload -> Telegram WebApp.openLink.
  await page.locator('header button').last().click()
  await page.getByLabel('Почта для карты и СБП').fill('Buyer2026@Mail.ru')
  await page.getByRole('button', { name: 'Карта / СБП', exact: true }).click()

  await page.waitForFunction(() => (
    Array.isArray(window.__openedLinks)
      && window.__openedLinks.includes('https://pay.example/e2e')
  ))

  assert.equal(paymentPayload?.provider, 'lava')
  assert.equal(paymentPayload?.customer_email, 'buyer2026@mail.ru')
  await page.getByRole('button', { name: 'Закрыть пополнение' }).click()

  // Trends E2E: server-side tag query + client-side filtering.
  await page.getByRole('button', { name: /Тренды/ }).click()
  await page.getByText('Curated Video', { exact: true }).waitFor()
  await page.getByText('Повтори фото с Pinterest', { exact: true }).waitFor()
  assert.equal(promptsPayload?.source, 'tag')
  assert.equal(promptsPayload?.tag, 'trend')
  assert.equal(await page.getByText('Ordinary Prompt', { exact: true }).count(), 0)

  // Generic user trend E2E: uploading alone must NOT start generation anymore.
  const curatedCard = page.locator('article').filter({ hasText: curatedTrend.title })
  await curatedCard.getByRole('button', { name: 'Повторить', exact: true }).click()
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
  await trendRunner.getByText('Сгенерировать · 1 фото', { exact: true }).waitFor()
  await page.waitForTimeout(100)
  assert.equal(trendGenerationPayload, null, 'Uploading a trend reference must not auto-run')

  const generatedResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith('/trends/run'),
  )
  await trendRunner.getByRole('button', { name: 'Сгенерировать · 1 фото', exact: true }).click()
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
  await taskDetailTitle.waitFor()
  await page.mouse.click(10, 10)
  await taskDetailTitle.waitFor({ state: 'hidden' })

  // Pinterest repeat E2E: Pinterest URL -> identity photo -> measurements -> explicit Create.
  await page.getByRole('button', { name: /Тренды/ }).click()
  const pinterestCard = page.locator('article').filter({ hasText: pinterestTrend.title })
  await pinterestCard.getByRole('button', { name: 'Повторить', exact: true }).click()
  const pinterestRunner = page.getByRole('dialog')
  await pinterestRunner.getByText('Повтори фото с Pinterest', { exact: true }).waitFor()
  await pinterestRunner.getByText('РЕФЕРЕНС', { exact: true }).waitFor()
  await pinterestRunner.getByText('ТЫ', { exact: true }).waitFor()

  const pinterestFileInputs = pinterestRunner.locator('input[type="file"]')
  assert.equal(await pinterestFileInputs.count(), 2)
  const createButton = pinterestRunner.getByRole('button', { name: 'Создать →', exact: true })
  assert.equal(await createButton.isDisabled(), true)

  const pinterestUrl = 'https://www.pinterest.com/pin/123456789/'
  await pinterestRunner.getByPlaceholder('Ссылка на пин с Pinterest').fill(pinterestUrl)
  const pinterestReferenceResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith('/trends/pinterest-reference'),
  )
  await pinterestRunner.getByRole('button', { name: 'Загрузить', exact: true }).click()
  await pinterestReferenceResponse

  assert.equal(pinterestReferencePayload?.url, pinterestUrl)
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
    'https://i.pinimg.com/736x/e2/e2/e2/reference.jpg',
    'https://cdn.example/pinterest-user.jpg',
  ])
  assert.equal(pinterestGenerationPayload?.height_cm, 172)
  assert.equal(pinterestGenerationPayload?.weight_kg, 64)
  for (const forbiddenField of [
    'model',
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

  console.log('Mini App critical browser E2E passed')
} finally {
  await browser?.close()
  server.kill('SIGTERM')
}
