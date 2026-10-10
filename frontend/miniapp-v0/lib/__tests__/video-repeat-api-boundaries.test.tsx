import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { bootstrapApp, fetchFeedItem, fetchTaskDetail, generateVideo, unpublishGeneration } from '../api'
import { notifyFeedChanged, mergePendingPublication } from '../feed-events'
import { hydrateSeedance25IdentityPreset } from '../seedance25-repeat'
import { VideoGeneratorForm } from '@/components/forms/video-generator-form'
import type { FeedItem, VideoModel, VideoPromptPreset } from '../types'

jest.mock('@/components/forms/scenario-select', () => ({ ScenarioSelect: ({ value }: { value: string }) => <span>{value}</span> }))
const respond = (data: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) })
const videoModel: VideoModel = { id: 'seedance_2', label: 'Seedance', description: 'Synthetic', supports: ['text', 'imgtxt', 'video'], durations: [5], ratios: ['16:9'], costs: { '5': 5 } }
const preset: VideoPromptPreset = { title: 'Repeat', prompt: '', promptHidden: true, model: videoModel.id, scenario: 'video', duration: 5, ratio: '16:9', sourceFeedGenId: 4217806990,
  repeatReferenceSlots: { version: 1, available: true, cost_multiplier: 2, images: [], videos: [{ index: 0, role: 'reference', binding: 'fixed' }] } }
const payload = { model: videoModel.id, scenario: 'video' as const, duration: 5, ratio: '16:9', sourceFeedGenId: preset.sourceFeedGenId, prompt: '', startImage: null, references: [], videoReferences: [] }
const fetchMock = jest.fn()
beforeEach(() => { fetchMock.mockReset(); global.fetch = fetchMock; window.sessionStorage.clear(); localStorage.clear(); window.Telegram!.WebApp!.initData = 'mock_init_data'; window.history.replaceState({}, '', '/mini-app/') })

it('normalizes an actual Omni feed card to the available public model', async () => {
  fetchMock.mockResolvedValueOnce(respond({ ok: true, feed_item: { id: 41, task_id: 'source-omni', model: 'gemini_omni_video', gen_type: 'video', is_mine: false, scenario: 'video', repeat_reference_slots: { version: 1, available: true, cost_multiplier: 1, images: [{ index: 0, role: 'reference', binding: 'fixed' }], videos: [] } } }))
  const item = await fetchFeedItem(41)
  const hydrated = await hydrateSeedance25IdentityPreset(item, { ...preset, sourceFeedGenId: 41, model: 'gemini_omni' })
  expect(hydrated.model).toBe('gemini_omni')
  render(<VideoGeneratorForm models={[{ ...videoModel, id: 'gemini_omni' }]} promptPreset={hydrated} onSubmit={jest.fn()} isSubmitting={false} credits={100} />)
  expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeEnabled()
})

it('withdraws the full publication through the installed scope endpoint', async () => {
  notifyFeedChanged({ id: 888, task_id: 'published-video', publication_scope: 'feed' } as FeedItem)
  fetchMock.mockResolvedValueOnce(respond({ ok: true, removed: true, publication_scope: 'private' }))
  await unpublishGeneration('published-video')
  expect(mergePendingPublication([], 'feed')).toEqual([])
  expect(mergePendingPublication([], 'profile')).toEqual([])
  expect(fetchMock.mock.calls[0][0]).toBe('/mini-app/api/generations/share')
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ init_data: 'mock_init_data', task_id: 'published-video', publication_scope: 'private' })
})

it('preserves accepted status and prevents duplicate HTTP submissions until the task is terminal', async () => {
  fetchMock.mockResolvedValueOnce(respond({ ok: false, code: 'video_status_pending', task_id: 'accepted-task', error: 'Accepted; awaiting status' }, false))
  await expect(generateVideo(payload)).rejects.toMatchObject({ code: 'video_status_pending', taskId: 'accepted-task' })
  await expect(generateVideo(payload)).rejects.toMatchObject({ code: 'video_status_pending' })
  expect(fetchMock).toHaveBeenCalledTimes(1)
  fetchMock.mockResolvedValueOnce(respond({ ok: true, task: { task_id: 'accepted-task', status: 'completed' } }))
  await fetchTaskDetail('accepted-task')
  fetchMock.mockResolvedValueOnce(respond({ ok: true, status: 'queued', task_id: 'next-task', cost: 10, credits: 80 }))
  await expect(generateVideo(payload)).resolves.toHaveProperty('task.task_id', 'next-task')
  expect(fetchMock).toHaveBeenCalledTimes(3)
})

it('shows accepted status after real HTTP failure and keeps it after the form is reopened', async () => {
  window.Telegram!.WebApp!.initData = 'user=%7B%22id%22%3A1%7D'
  fetchMock.mockResolvedValueOnce(respond({ ok:true,quote_id:'a'.repeat(32),quote_hash:'b'.repeat(64),cost:10,charge_cost:10,input_seconds:5,selected_output_seconds:5 }))
  fetchMock.mockResolvedValueOnce(respond({ ok: false, code: 'video_status_pending', task_id: 'accepted-task', error: 'Accepted; awaiting status' }, false))
  const props = { models: [videoModel], promptPreset: preset, onSubmit: async (data: Parameters<typeof generateVideo>[0]) => { await generateVideo(data) }, isSubmitting: false, credits: 100 }
  const view = render(<VideoGeneratorForm {...props} />)
  await waitFor(() => expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: /Запустить видео/ }))
  await screen.findByText('Видео принято, ожидаем подтверждения статуса')
  expect(screen.queryByText(/Откройте публикацию заново/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeDisabled()
  view.unmount()
  render(<VideoGeneratorForm {...props} promptPreset={{ ...preset }} />)
  expect(screen.getByText('Видео принято, ожидаем подтверждения статуса')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeDisabled()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})


it('preserves the published cache and grant context when full withdrawal fails', async () => {
  const published = { id: 889, task_id: 'failed-withdrawal', publication_scope: 'feed' } as FeedItem
  notifyFeedChanged(published)
  fetchMock.mockResolvedValueOnce(respond({ ok: false, error: 'Synthetic unavailable' }, false))
  await expect(unpublishGeneration('failed-withdrawal')).rejects.toThrow('Synthetic unavailable')
  expect(mergePendingPublication([], 'feed')).toEqual([published])
})

it('keeps acceptance without a task ID through empty or pending history refreshes', async () => {
  const unknown = { ...payload, sourceFeedGenId: 4217806991 }
  fetchMock.mockResolvedValueOnce(respond({ ok: false, code: 'video_status_pending', error: 'Accepted; awaiting status' }, false))
  await expect(generateVideo(unknown)).rejects.toMatchObject({ code: 'video_status_pending' })
  fetchMock.mockResolvedValueOnce(respond({ ok: true, recent_tasks: [] }))
  await bootstrapApp()
  await expect(generateVideo(unknown)).rejects.toMatchObject({ code: 'video_status_pending' })
  expect(fetchMock).toHaveBeenCalledTimes(2)
  render(<VideoGeneratorForm models={[videoModel]} promptPreset={{ ...preset, sourceFeedGenId: unknown.sourceFeedGenId }} onSubmit={jest.fn()} isSubmitting={false} credits={100} />)
  expect(screen.getByText('Видео принято, ожидаем подтверждения статуса')).toBeInTheDocument()
  expect(screen.queryByText(/Откройте публикацию заново/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeDisabled()
})


it('uses retained-quality server duration quotes from an actual Seedance feed response', async () => {
  fetchMock.mockResolvedValueOnce(respond({ ok: true, feed_item: { id: 480, task_id: 'source-480p', model: 'seedance_2_5', gen_type: 'video', is_mine: false, scenario: 'video', repeat_reference_slots: {
    version: 1, available: true, cost_multiplier: 2, pricing_quality: '480p', duration_costs: { '5': 4, '10': 8 },
    images: [], videos: [{ index: 0, role: 'reference', binding: 'fixed' }],
  } } }))
  const item = await fetchFeedItem(480)
  const hydrated = await hydrateSeedance25IdentityPreset(item, { ...preset, model: 'seedance_2_5', sourceFeedGenId: 480 })
  fetchMock.mockImplementation(async (_url, options) => {
    const body = JSON.parse(options.body)
    const output = body.v_duration
    return respond({ ok:true, quote_id:'a'.repeat(32), quote_hash:'b'.repeat(64), cost: output === 5 ? 4 : 6,
      charge_cost:output === 5 ? 4 : 6,input_seconds:5,selected_output_seconds:output })
  })
  const onSubmit = jest.fn()
  render(<VideoGeneratorForm models={[{ ...videoModel, id: 'seedance_2_5', durations: [5, 10], costs: { '5': 5, '10': 10 } }]} promptPreset={hydrated} onSubmit={onSubmit} isSubmitting={false} credits={4} />)
  await waitFor(() => expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeEnabled())
  expect(screen.getByText('4', { exact: true })).toBeInTheDocument()
  expect(screen.getByText('Вход 5 с + результат 5 с')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /10с/ }))
  expect(await screen.findByText('6', { exact: true })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeDisabled()
  expect(onSubmit).not.toHaveBeenCalled()
})


it.each([undefined, {}, { '10': 8 }, { '5': 0 }, { '5': -1 }, { '5': '4' }])('blocks missing or unusable retained-quality quote %s', (duration_costs) => {
  const unpriced = { ...preset, model: 'seedance_2_5', repeatReferenceSlots: { ...preset.repeatReferenceSlots!, duration_costs } } as VideoPromptPreset
  render(<VideoGeneratorForm models={[{ ...videoModel, id: 'seedance_2_5' }]} promptPreset={unpriced} onSubmit={jest.fn()} isSubmitting={false} credits={100} />)
  expect(screen.getByRole('button', { name: /Запустить видео/ })).toBeDisabled()
  expect(screen.getByText('Стоимость недоступна')).toBeInTheDocument()
})
