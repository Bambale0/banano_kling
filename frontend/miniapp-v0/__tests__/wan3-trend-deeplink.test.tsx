import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AppProvider, useApp } from '@/lib/app-context'
import { TrendsTab } from '@/components/tabs/trends-tab'
import { isWanTrendItem } from '@/lib/trend-settings'
import type { PromptItem } from '@/lib/types'
import * as api from '@/lib/api'
import * as wanApi from '@/lib/wan3-prime-api'

jest.mock('@/lib/api', () => ({
  bootstrapApp: jest.fn(), fetchPromptDetail: jest.fn(), fetchPrompts: jest.fn(), fetchFeedItem: jest.fn(), fetchTaskDetail: jest.fn(),
  getInitData: () => '', getApiBasePath: () => '/api', hasTelegramInitData: () => true, waitForTelegramInitData: async () => true,
  getStartParamFallback: () => new URLSearchParams(window.location.search).get('startapp') || '',
  submitPrompt: jest.fn(), uploadFile: jest.fn(), deactivatePrompt: jest.fn(), fetchPromptLink: jest.fn(),
}))
jest.mock('@/lib/mock-data', () => ({ mockAppState: { paymentPackages: [] }, mockImageModels: [], mockVideoModels: [] }))
jest.mock('@/lib/clipboard', () => ({ copyTextToClipboard: jest.fn() }))
jest.mock('@/lib/seedance-trend-admin-api', () => ({ publishSeedanceTrendUpload: jest.fn() }))
jest.mock('@/components/seedance-trend-upload-references', () => ({ SeedanceTrendUploadReferences: () => null, emptySeedanceUploadReferences: () => ({ images: [], videos: [], audios: [] }) }))
jest.mock('@/lib/trend-admin-api', () => ({ updateTrendPreview: jest.fn() }))
jest.mock('@/lib/media-url', () => ({ normalizeMiniAppMediaUrl: (value: string) => value, mediaAspectRatio: () => '1:1', videoPreviewFrameUrl: () => '' }))
jest.mock('@/lib/trend-price', () => ({ ...jest.requireActual('@/lib/trend-price') }))
jest.mock('@/lib/genjutsu-api', () => ({ genjutsuCall: jest.fn().mockResolvedValue({ items: [] }), openGenjutsu: jest.fn() }))
jest.mock('@/lib/seedance25-repeat', () => ({ hydrateSeedance25IdentityPreset: jest.fn() }))
jest.mock('@/lib/trend-api', () => ({ createTrendRunRequestId: () => 'synthetic', runTrend: jest.fn(), runPinterestRepeatTrend: jest.fn(), TrendRunRequestError: class extends Error {} }))
jest.mock('@/components/ui/dialog', () => ({
  Dialog: ({ open, children }: any) => open ? <div>{children}</div> : null,
  DialogContent: ({ children }: any) => <div>{children}</div>,
  DialogTitle: ({ children }: any) => <h2>{children}</h2>,
}))
jest.mock('@/lib/wan3-prime-api', () => ({
  ...jest.requireActual('@/lib/wan3-prime-api'),
  fetchWan3PrimeTrendPlan: jest.fn(), fetchWan3PrimeRepeatPlan: jest.fn(), fetchWan3PrimeOwnerRecipe: jest.fn(),
  quoteWan3Prime: jest.fn(), generateWan3Prime: jest.fn(), uploadWan3PrimeReference: jest.fn(), importWan3PrimeReference: jest.fn(),
}))
const apiMock = api as jest.Mocked<typeof api>
const wanMock = wanApi as jest.Mocked<typeof wanApi>
const models = ['wan_3', 'wan_3_prime', 'other_video'].map(id => ({ id, label: id, supports: ['text', 'imgtxt'], ratios: ['16:9'], durations: [5], costs: {} }))
const card = (model: 'wan_3' | 'wan_3_prime', publicCard = true): PromptItem => ({
  id: 731, title: 'Synthetic WAN trend', description: 'Repeat my scene', prompt_text: '', category: 'video', tags: ['trend', 'trend-video'],
  model: publicCard ? null : model, generation_settings: { kind: 'video', wan3_recipe_version: 1, preview_type: 'video' },
  author_id: 2, status: 'approved', likes: 0, uses_count: 0,
} as PromptItem)
const plan = (model: 'wan_3' | 'wan_3_prime'): wanApi.Wan3PrimeRepeatPlan => ({
  ok: true, trend_id: 731, repeat_plan_hash: 'synthetic-plan',
  recipe: { model, scenario: 'reference', prompt: '', resolution: '720P', aspect_ratio: '9:16', duration: 8, audio: true, nsfw_checker: false },
  slots: [{ key: 'image:0', kind: 'image', role: 'reference', index: 0, binding: 'upload' }],
})
let expectedGenerateCalls = 0
let expectedQuoteCalls = 0
let current: ReturnType<typeof useApp>
function Probe() { current = useApp(); return <TrendsTab /> }
beforeEach(() => {
  jest.clearAllMocks()
  expectedGenerateCalls = 0; expectedQuoteCalls = 0
  window.history.replaceState({}, '', '/')
  apiMock.bootstrapApp.mockResolvedValue({ ok: true, is_admin: false, telegram_id: 1, first_name: 'Synthetic', credits: 0, mini_app_url: '',
    image_models: [], video_models: models, recent_tasks: [], saved_references: [] } as any)
  apiMock.fetchPrompts.mockResolvedValue([])
})
afterEach(() => {
  expect(wanMock.generateWan3Prime).toHaveBeenCalledTimes(expectedGenerateCalls)
  expect(wanMock.quoteWan3Prime).toHaveBeenCalledTimes(expectedQuoteCalls)
  expect(wanMock.fetchWan3PrimeRepeatPlan).not.toHaveBeenCalled()
})

async function expectPrivatePlan(model: 'wan_3' | 'wan_3_prime') {
  await waitFor(() => expect(wanMock.fetchWan3PrimeTrendPlan).toHaveBeenCalledWith(731, expect.any(AbortSignal)))
  await screen.findByLabelText('Загрузить Image1')
  expect(screen.getByRole('heading', { name: model === 'wan_3' ? 'Wan 3.0 Video' : 'Wan 3.0 Video Prime' })).toBeInTheDocument()
  expect(current.videoPromptPreset).toBeNull()
  expect(current.trendToRun?.id).toBe(731)
}

test.each(['wan_3', 'wan_3_prime'] as const)('ordinary marker-only catalog card adopts private %s plan', async model => {
  const publicCard = card(model)
  expect(publicCard.model).toBeNull()
  expect(publicCard.generation_settings).not.toHaveProperty('model')
  expect(publicCard.generation_settings).not.toHaveProperty('wan3_recipe')
  apiMock.fetchPrompts.mockResolvedValue([publicCard])
  wanMock.fetchWan3PrimeTrendPlan.mockResolvedValue(plan(model))
  render(<AppProvider><Probe /></AppProvider>)
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить', exact: true }))
  await expectPrivatePlan(model)
})

test.each([
  ['wan_3', true], ['wan_3_prime', true], ['wan_3', false], ['wan_3_prime', false],
] as const)('shared prompt link routes %s (public=%s) through private plan', async (model, publicCard) => {
  window.history.replaceState({}, '', '/?startapp=prompt_731_ref_SYNTHETIC')
  apiMock.fetchPromptDetail.mockResolvedValue(card(model, publicCard))
  wanMock.fetchWan3PrimeTrendPlan.mockResolvedValue(plan(model))
  render(<AppProvider><Probe /></AppProvider>)
  await expectPrivatePlan(model)
  expect(current.activeTab).toBe(5)
})

test('missing private plan fails closed and permits retry without generic routing', async () => {
  window.history.replaceState({}, '', '/?startapp=prompt_731')
  apiMock.fetchPromptDetail.mockResolvedValue(card('wan_3'))
  wanMock.fetchWan3PrimeTrendPlan.mockRejectedValueOnce(new wanApi.Wan3PrimeApiError('private missing record', 'not_found', 404))
    .mockResolvedValueOnce(plan('wan_3'))
  render(<AppProvider><Probe /></AppProvider>)
  await screen.findByText('Тренд недоступен для повтора. Попросите автора опубликовать его заново.')
  expect(current.videoPromptPreset).toBeNull()
  expect(screen.queryByText('private missing record')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Запустить Wan' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку рецепта' }))
  await expectPrivatePlan('wan_3')
})

test('non-WAN video deep link keeps generic video behavior', async () => {
  window.history.replaceState({}, '', '/?startapp=prompt_731')
  apiMock.fetchPromptDetail.mockResolvedValue({ ...card('wan_3', false), model: 'other_video', generation_settings: { kind: 'video', model: 'other_video' } })
  render(<AppProvider><Probe /></AppProvider>)
  await waitFor(() => expect(current.videoPromptPreset?.model).toBe('other_video'))
  expect(current.activeTab).toBe(2)
  expect(current.trendToRun).toBeNull()
  expect(wanMock.fetchWan3PrimeTrendPlan).not.toHaveBeenCalled()
})

test('WAN detection accepts safe version 1 or admin model and rejects other markers', () => {
  expect(isWanTrendItem(card('wan_3'))).toBe(true)
  expect(isWanTrendItem({ ...card('wan_3', false), generation_settings: null })).toBe(true)
  expect(isWanTrendItem({ ...card('wan_3'), generation_settings: { kind: 'video', wan3_recipe_version: 2 } as any })).toBe(false)
})

test('marker-only WAN3 keeps its private-plan model in optimistic history when generation omits model', async () => {
  expectedGenerateCalls = 1; expectedQuoteCalls = 1
  window.history.replaceState({}, '', '/?startapp=prompt_731')
  apiMock.fetchPromptDetail.mockResolvedValue(card('wan_3'))
  wanMock.fetchWan3PrimeTrendPlan.mockResolvedValue(plan('wan_3'))
  wanMock.uploadWan3PrimeReference.mockResolvedValue({ url: 'https://owned.test/replacement.png' } as any)
  wanMock.quoteWan3Prime.mockResolvedValue({ ok: true, quote_hash: 'synthetic-quote', reserve_cost: 0, billing_duration_seconds: 8, source_video_duration_seconds: 0, tariff_missing: false, admin_free: false, auto_duration: false })
  wanMock.generateWan3Prime.mockResolvedValue({ ok: true, status: 'queued', internal_task_id: 'synthetic-only', reserve_cost: 0 })
  render(<AppProvider><Probe /></AppProvider>)
  await expectPrivatePlan('wan_3')
  fireEvent.change(screen.getByLabelText('Загрузить Image1'), { target: { files: [new File(['synthetic'], 'replacement.png', { type: 'image/png' })] } })
  const launch = await screen.findByRole('button', { name: 'Запустить Wan' })
  await waitFor(() => expect(launch).toBeEnabled())
  fireEvent.click(launch)
  await waitFor(() => expect(current.state.recentTasks[0]?.task_id).toBe('synthetic-only'))
  expect(current.state.recentTasks[0]).toMatchObject({ model: 'wan_3', model_label: 'Wan 3.0 Video' })
  expect(wanMock.generateWan3Prime).toHaveBeenCalledWith(expect.objectContaining({ recipe: expect.objectContaining({ model: 'wan_3', trend_id: 731 }) }))
})

test('ordinary WAN prompt without trend tags does not become a private trend repeat', async () => {
  window.history.replaceState({}, '', '/?startapp=prompt_731')
  apiMock.fetchPromptDetail.mockResolvedValue({ ...card('wan_3', false), tags: [], generation_settings: { kind: 'video', model: 'wan_3' } })
  render(<AppProvider><Probe /></AppProvider>)
  await waitFor(() => expect(current.videoPromptPreset?.model).toBe('wan_3'))
  expect(current.trendToRun).toBeNull()
  expect(wanMock.fetchWan3PrimeTrendPlan).not.toHaveBeenCalled()
})
