import { generateVideo, readPendingMeasuredVideo, recoverPendingMeasuredVideo, type VideoSubmission } from '../api'
import { readPendingTrend, recoverPendingTrend } from '../trend-api'

const id = 'a'.repeat(32)
const payload = { model: 'seedance_2', scenario: 'video', ratio: '16:9', duration: 5,
  prompt: 'synthetic', startImage: null, videoReferences: ['https://example.test/source.mp4'], references: [],
  videoQuoteId: id, videoQuoteHash: 'b'.repeat(64) } as VideoSubmission
const reply = (body: object, status = 200) => ({ ok: status < 400, status, headers: new Headers({ 'content-type': 'application/json' }), text: async () => JSON.stringify(body) })
function saveVideo() { localStorage.setItem('measured-video-pending:1', JSON.stringify(payload)) }
function saveTrend() { localStorage.setItem('trend-quote-pending:1', JSON.stringify({ model: 'seedance_2', quoteId: id,
  refs: ['https://example.test/source.mp4'], payload: { trend_id: 42, video_quote_id: id, video_quote_hash: 'b'.repeat(64) } })) }

beforeEach(() => {
  localStorage.clear(); sessionStorage.clear()
  window.history.replaceState({}, '', '/mini-app/')
  window.Telegram!.WebApp!.initData = 'user=' + encodeURIComponent(JSON.stringify({ id: 1 }))
})
afterEach(() => jest.restoreAllMocks())

test('terminal missing video receipt clears pending but surfaces the error', async () => {
  saveVideo()
  global.fetch = jest.fn().mockResolvedValue(reply({ ok: false, code: 'video_quote_missing', error: 'Missing quote' }, 404))
  await expect(recoverPendingMeasuredVideo()).rejects.toThrow('Missing quote')
  expect(readPendingMeasuredVideo()).toBeNull()
})

test('unknown and server outage preserve video receipt', async () => {
  saveVideo()
  global.fetch = jest.fn().mockResolvedValueOnce(reply({ ok: true, status: 'outcome_unknown' }))
    .mockResolvedValueOnce(reply({ ok: false, error: 'Temporarily unavailable' }, 503))
  expect((await recoverPendingMeasuredVideo()).status).toBe('outcome_unknown')
  await expect(recoverPendingMeasuredVideo()).rejects.toThrow()
  expect(readPendingMeasuredVideo()?.videoQuoteId).toBe(id)
})

test('missing trend receipt is terminal and is not polled forever', async () => {
  saveTrend()
  global.fetch = jest.fn().mockResolvedValue(reply({ ok: false, code: 'video_quote_missing', error: 'Missing quote' }, 404))
  await expect(recoverPendingTrend()).rejects.toThrow('Missing quote')
  expect(readPendingTrend()).toBeNull()
  expect(await recoverPendingTrend()).toBeNull()
  expect(global.fetch).toHaveBeenCalledTimes(1)
})

test('expired quoted trend stops automatic launch retries and requires a new explicit quote', async () => {
  saveTrend()
  global.fetch = jest.fn().mockResolvedValueOnce(reply({ ok: true, status: 'quoted' }))
    .mockResolvedValueOnce(reply({ ok: false, code: 'video_quote_changed', error: 'Price expired' }, 409))
  await expect(recoverPendingTrend()).rejects.toThrow('Price expired')
  expect(readPendingTrend()).toBeNull()
  await recoverPendingTrend()
  expect(global.fetch).toHaveBeenCalledTimes(2)
})

test('late accepted video A cannot remove a newer persisted video B', async () => {
  let resolve!: (value: unknown) => void
  global.fetch = jest.fn().mockImplementation(() => new Promise(done => { resolve = done }))
  const pending = generateVideo(payload)
  localStorage.setItem('measured-video-pending:1', JSON.stringify({ ...payload, videoQuoteId: 'c'.repeat(32) }))
  resolve(reply({ ok: true, status: 'queued', task_id: 'accepted-a', credits: 52, cost: 48, model_label: 'Seedance' }))
  await pending
  expect(readPendingMeasuredVideo()?.videoQuoteId).toBe('c'.repeat(32))
})


test.each(['status', 'resubmit'])('trend %s outage preserves the same durable receipt', async phase => {
  saveTrend()
  const fetchMock = jest.fn()
  if (phase === 'resubmit') fetchMock.mockResolvedValueOnce(reply({ ok: true, status: 'quoted' }))
  fetchMock.mockResolvedValue(reply({ ok: false, error: 'Unavailable' }, 503))
  global.fetch = fetchMock
  await expect(recoverPendingTrend()).rejects.toThrow('Unavailable')
  expect(readPendingTrend()?.quoteId).toBe(id)
})
