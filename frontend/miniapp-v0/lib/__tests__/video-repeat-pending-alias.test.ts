import { bootstrapApp, fetchTaskDetail, generateVideo } from '../api'

const respond = (data: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) })
const payload = { model: 'seedance_2', scenario: 'video' as const, duration: 5, ratio: '16:9', sourceFeedGenId: 4218169990, prompt: '', startImage: null, references: [], videoReferences: [] }
const fetchMock = jest.fn()
const settleResponses = () => new Promise((resolve) => setTimeout(resolve, 0))
beforeEach(() => { fetchMock.mockReset(); global.fetch = fetchMock; window.sessionStorage.clear(); window.history.replaceState({}, '', '/mini-app/') })
async function acceptedReceipt() {
  fetchMock.mockResolvedValueOnce(respond({ ok: false, code: 'video_status_pending', task_id: 'video_repeat_receipt_local', error: 'Pending' }, false))
  await expect(generateVideo(payload)).rejects.toMatchObject({ code: 'video_status_pending', taskId: 'video_repeat_receipt_local' })
}

it('clears the exact local receipt after its owned detail resolves to a terminal canonical task', async () => {
  await acceptedReceipt()
  fetchMock.mockResolvedValueOnce(respond({ ok: true, task: { task_id: 'provider-canonical', status: 'completed' } }))
  await fetchTaskDetail('video_repeat_receipt_local')
  expect(JSON.parse(fetchMock.mock.calls[1][1].body).task_id).toBe('video_repeat_receipt_local')
  fetchMock.mockResolvedValueOnce(respond({ ok: true, status: 'queued', task_id: 'next-task', cost: 10, credits: 80 }))
  await expect(generateVideo(payload)).resolves.toHaveProperty('task.task_id', 'next-task')
  expect(fetchMock).toHaveBeenCalledTimes(3)
})

it('resolves promotion through existing bootstrap and later clears only the canonical terminal task', async () => {
  await acceptedReceipt()
  fetchMock.mockResolvedValueOnce(respond({ ok: true, recent_tasks: [{ task_id: 'unrelated-task', status: 'completed', source_feed_gen_id: payload.sourceFeedGenId }] }))
  fetchMock.mockResolvedValueOnce(respond({ ok: true, task: { task_id: 'provider-canonical', status: 'pending' } }))
  await bootstrapApp()
  await settleResponses()
  expect(fetchMock.mock.calls[2][0]).toBe('/mini-app/api/task-detail')
  expect(JSON.parse(fetchMock.mock.calls[2][1].body).task_id).toBe('video_repeat_receipt_local')
  await expect(generateVideo(payload)).rejects.toMatchObject({ code: 'video_status_pending', taskId: 'provider-canonical' })
  expect(fetchMock).toHaveBeenCalledTimes(3)
  fetchMock.mockResolvedValueOnce(respond({ ok: true, recent_tasks: [{ task_id: 'provider-canonical', status: 'completed' }] }))
  await bootstrapApp()
  await settleResponses()
  fetchMock.mockResolvedValueOnce(respond({ ok: true, status: 'queued', task_id: 'next-task', cost: 10, credits: 80 }))
  await expect(generateVideo(payload)).resolves.toHaveProperty('task.task_id', 'next-task')
  expect(fetchMock).toHaveBeenCalledTimes(5)
})

it('keeps a receipt blocked when alias lookup fails and same-source unrelated history is terminal', async () => {
  await acceptedReceipt()
  fetchMock.mockResolvedValueOnce(respond({ ok: true, recent_tasks: [{ task_id: 'unrelated-task', status: 'failed', source_feed_gen_id: payload.sourceFeedGenId }] }))
  fetchMock.mockResolvedValueOnce(respond({ ok: false, error: 'Temporarily unavailable' }, false))
  await bootstrapApp()
  await settleResponses()
  await expect(generateVideo(payload)).rejects.toMatchObject({ code: 'video_status_pending', taskId: 'video_repeat_receipt_local' })
  fetchMock.mockResolvedValueOnce(respond({ ok: true, task: { task_id: 'unrelated-task', status: 'completed' } }))
  await fetchTaskDetail('unrelated-task')
  await expect(generateVideo(payload)).rejects.toMatchObject({ code: 'video_status_pending' })
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/generate-video'))).toHaveLength(1)
})


it.each([403, 404, 'empty'])('does not clear a pending receipt after denied or empty detail %s', async (outcome) => {
  await acceptedReceipt()
  fetchMock.mockResolvedValueOnce(respond({ ok: true, recent_tasks: [] }))
  fetchMock.mockResolvedValueOnce(outcome === 'empty' ? respond({ ok: true, task: null }) : { ...respond({ ok: false, error: 'Unavailable' }, false), status: outcome })
  await bootstrapApp()
  await settleResponses()
  await expect(generateVideo(payload)).rejects.toMatchObject({ code: 'video_status_pending', taskId: 'video_repeat_receipt_local' })
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/generate-video'))).toHaveLength(1)
})

it('deduplicates simultaneous bootstrap alias lookups without submitting another generation', async () => {
  await acceptedReceipt()
  let finish!: (response: ReturnType<typeof respond>) => void
  fetchMock.mockImplementation((url: string) => url.endsWith('/bootstrap')
    ? Promise.resolve(respond({ ok: true, recent_tasks: [] }))
    : new Promise((resolve) => { finish = resolve }))
  const first = bootstrapApp()
  const second = bootstrapApp()
  // Bootstrap must resolve while its deduplicated alias read is still pending.
  await Promise.all([first, second])
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/task-detail'))).toHaveLength(1)
  finish(respond({ ok: true, task: { task_id: 'provider-canonical', status: 'pending' } }))
  await settleResponses()
  await expect(generateVideo(payload)).rejects.toMatchObject({ code: 'video_status_pending', taskId: 'provider-canonical' })
  expect(fetchMock.mock.calls.filter(([url]) => url.endsWith('/generate-video'))).toHaveLength(1)
})
