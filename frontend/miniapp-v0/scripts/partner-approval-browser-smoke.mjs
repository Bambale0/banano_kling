import { chromium } from 'playwright'

const baseUrl = process.env.PARTNER_BROWSER_URL || 'http://127.0.0.1:4173/mini-app/'
const referralLink = 'https://t.me/example_bot?start=ref_BROWSERTEST'
let partnerStatus = 'partner'
let firstLinePercent = 30
let applyCalls = 0
let overviewCalls = 0

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 430, height: 900 } })

try {
  await page.addInitScript(() => {
    const initData = 'query_id=browser-test&user=%7B%22id%22%3A710099%2C%22first_name%22%3A%22Browser%22%7D&auth_date=1786200000&hash=test'
    window.__BANANO_TG_INIT_DATA__ = initData
    window.Telegram = {
      WebApp: {
        initData,
        initDataUnsafe: {},
        ready() {},
        expand() {},
      },
    }
    try {
      window.sessionStorage.setItem('__banano_tg_init_data', initData)
    } catch {}
  })

  await page.route('**/mini-app/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname

    if (path.endsWith('/api/bootstrap')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          telegram_id: 710099,
          first_name: 'Browser',
          last_name: 'Test',
          telegram_username: 'browser_test',
          photo_url: '',
          referral_code: 'BROWSERTEST',
          profile_link: '',
          referral_link: '',
          channel_url: '',
          prompt_repeat_balance_rub: 0,
          prompt_repeat_total_rub: 0,
          bot_username: 'example_bot',
          credits: 5,
          is_admin: false,
          mini_app_url: baseUrl,
          actions: [],
          payment_packages: [],
          image_models: [],
          video_models: [],
          recent_tasks: [],
          saved_references: [],
        }),
      })
      return
    }

    if (path.endsWith('/api/partner-overview')) {
      overviewCalls += 1
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          is_partner: true,
          percent: firstLinePercent,
          level2_percent: 7,
          referrals_count: 12,
          balance_rub: 345.5,
          prompt_repeat_balance_rub: 0,
          prompt_repeat_total_rub: 0,
          channel_url: '',
          referral_link: referralLink,
          status: partnerStatus,
        }),
      })
      return
    }

    if (path.endsWith('/api/action')) {
      const body = JSON.parse(route.request().postData() || '{}')
      if (body.action === 'partner_apply') {
        applyCalls += 1
        partnerStatus = 'partner'
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true, status: 'approved', application_id: null, created: false }),
        })
        return
      }
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    })
  })

  await page.goto(baseUrl, { waitUntil: 'networkidle' })

  await page.getByRole('button', { name: /Сервисы/i }).click()
  await page.getByRole('button', { name: /Партнёрам/i }).click()

  await page.getByText('Ваш партнёрский кабинет', { exact: true }).waitFor()
  await page.getByText(referralLink, { exact: true }).waitFor()
  await page.getByRole('button', { name: /Скопировать ссылку/i }).waitFor()
  await page.getByText(/1 уровня: 30%/).waitFor()
  assert((await page.getByRole('button', { name: /Активировать ссылку|Подать заявку/i }).count()) === 0, 'Obsolete activation UI is still visible')

  for (const historicalStatus of ['pending', 'rejected', 'available']) {
    partnerStatus = historicalStatus
    await page.getByRole('button', { name: 'Обновить', exact: true }).click()
    await page.getByText(referralLink, { exact: true }).waitFor()
    await page.waitForFunction(() => !document.querySelector('button[disabled] .animate-spin'))
  }
  for (const assignedPercent of [40, 0]) {
    firstLinePercent = assignedPercent
    await page.getByRole('button', { name: 'Обновить', exact: true }).click()
    await page.getByText(new RegExp(`1 уровня: ${assignedPercent}%`)).waitFor()
  }
  await page.getByText(/2 уровня: 7%/).waitFor()
  for (const width of [320, 390, 430]) {
    await page.setViewportSize({ width, height: 900 })
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Partner cabinet overflows at ${width}px`)
  }
  assert(applyCalls === 0, `Unexpected partner_apply calls: ${applyCalls}`)
  assert(overviewCalls >= 4, `Expected initial overview and refreshes, got ${overviewCalls}`)
  console.log(`open partner cabinet browser smoke: ok; overviewCalls=${overviewCalls}; applyCalls=${applyCalls}`)

} finally {
  await browser.close()
}
