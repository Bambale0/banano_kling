import { fetchTaskHistory } from '../api'

const fetchMock = jest.fn()
const originalFetch = global.fetch

beforeEach(() => {
  fetchMock.mockReset()
  global.fetch = fetchMock
  window.sessionStorage.clear()
  window.history.replaceState({}, '', '/mini-app/')
  window.Telegram!.WebApp!.initData = 'signed-telegram-launch'
})

afterAll(() => { global.fetch = originalFetch })

function historyWithMedia(url: string) {
  const payload = { ok: true, recent_tasks: [{ task_id: 'owned-task',
    result_url: url, result_urls: [url], preview_url: url,
    references: [{ url }],
  }], next_cursor: null }
  fetchMock.mockResolvedValue({ ok: true, status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(payload),
  })
  return fetchTaskHistory()
}

test.each([
  ['neuromixbot.com', '/uploads/results/image.png'],
  ['neuromixbot.com', '/uploads/refs/image/123/reference.jpg'],
  ['neuromixbot.com', '/uploads/wan3_prime/video.mp4'],
  ['tanyapi.chillcreative.ru', '/uploads/result.png'],
  ['tanyapp.chillcreative.ru', '/uploads/result.png'],
  ['tanyapp.xn--e1aikcel5c5a.online', '/uploads/result.png'],
  ['neuromixbot.com', '/uploads/feed/thumbs/poster.webp'],
])('history media uses the active app origin instead of %s%s', async (host, path) => {
  const url = `https://${host}${path}?signature=preserved#frame`
  const page = await historyWithMedia(url)
  const expected = `${window.location.origin}${path}?signature=preserved#frame`
  expect(page.recent_tasks[0]).toMatchObject({ result_url: expected,
    result_urls: [expected], preview_url: expected, references: [{ url: expected }],
  })
  expect(fetchMock.mock.calls[0][0]).toBe('/mini-app/api/task-history')
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).init_data).toBe('signed-telegram-launch')
})

test.each([
  'https://provider.example/uploads/result.png',
  'https://neuromixbot.com.attacker.example/uploads/result.png',
  'https://neuromixbot.com/mini-app/?startapp=sample',
  'https://neuromixbot.com/uploads-other/result.png',
])('preserves external providers, lookalikes and nonmedia URLs: %s', async url => {
  const page = await historyWithMedia(url)
  expect(page.recent_tasks[0].result_url).toBe(url)
})
