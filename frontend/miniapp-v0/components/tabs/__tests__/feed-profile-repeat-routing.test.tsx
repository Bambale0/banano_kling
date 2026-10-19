import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { FeedTab } from '../feed-tab'
import { ProfileTab } from '../profile-tab'
import { useApp } from '@/lib/app-context'
import { fetchFeed, fetchMyFeed, fetchPartnerOverview } from '@/lib/api'
import { hydrateSeedance25IdentityPreset } from '@/lib/seedance25-repeat'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/seedance25-repeat', () => ({ hydrateSeedance25IdentityPreset: jest.fn(async (_item, preset) => preset) }))
jest.mock('@/lib/genjutsu-api', () => ({ openGenjutsu: jest.fn() }))
jest.mock('@/lib/api', () => ({
  fetchFeed: jest.fn(), fetchMyFeed: jest.fn(), fetchProfileFeed: jest.fn(), fetchPartnerOverview: jest.fn(),
  addFeedComment: jest.fn(), fetchFeedComments: jest.fn(), likeFeedItem: jest.fn(), removeFeedItem: jest.fn(),
  setFeedItemBlurred: jest.fn(), shareFeedItem: jest.fn(), saveProfileChannel: jest.fn(),
}))
const cases = ['feed', 'profile'].flatMap(surface => ['image', 'video'].map(kind => [surface, kind]))
const context = () => ({ state: { mode: 'live', smartRepeatEnabled: true,
  user: { credits: 100, isAdmin: false }, imageModels: [{ id: 'banana_pro', label: 'Nano Banana Pro' }],
  videoModels: [{ id: 'seedance_2_5', label: 'Seedance 2.5' }], recentTasks: [], savedReferences: [], paymentPackages: [] },
  feedDeepLink: null, viewedProfileCode: null, consumeFeedDeepLink: jest.fn(),
  openSmartRepeat: jest.fn(), setActiveTab: jest.fn(), setPromptPreset: jest.fn(), setVideoPromptPreset: jest.fn(), openProfile: jest.fn() })
async function mount(surface: string, kind: string, smart: boolean, model = 'source-model-not-in-catalog') {
  const app = context(); app.state.smartRepeatEnabled = smart
  ;(useApp as jest.Mock).mockReturnValue(app)
  const item = { id: 42, task_id: 'source', model, gen_type: kind,
    result_url: kind === 'image' ? 'https://example.test/result.jpg' : 'https://example.test/result.mp4',
    result_urls: [], prompt: '', prompt_hidden: true, references_hidden: true,
    reference_images: [], reference_videos: [], aspect_ratio: '9:16', duration: 5, scenario: 'video',
    author: 'Synthetic author', is_mine: false, is_profile_visible: true, publication_scope: surface,
    likes_count: 0, shares_count: 0, comments_count: 0, remixes: 0, score: 0, created_at: '2026-10-19' }
  ;(fetchFeed as jest.Mock).mockResolvedValue({ feed: [item], models: [] })
  ;(fetchMyFeed as jest.Mock).mockResolvedValue([item])
  ;(fetchPartnerOverview as jest.Mock).mockResolvedValue({})
  render(surface === 'feed' ? <FeedTab /> : <ProfileTab />)
  fireEvent.click(await screen.findByRole('button', { name: surface === 'profile' ? 'Открыть публикацию' : kind === 'image' ? 'Открыть фото' : 'Открыть видео' }))
  const repeat = await screen.findByRole('button', { name: /^Повторить/ })
  await act(async () => { fireEvent.click(repeat) })
  return app
}
beforeEach(() => { jest.clearAllMocks(); window.sessionStorage.clear() })
test.each(cases)('%s %s smart repeat opens directly, without legacy hydration or a generator tab', async (surface, kind) => {
  const app = await mount(surface, kind, true)
  await waitFor(() => expect(app.openSmartRepeat).toHaveBeenCalledWith(42))
  expect(app.setActiveTab).not.toHaveBeenCalled()
  expect(app.setPromptPreset).not.toHaveBeenCalled()
  expect(app.setVideoPromptPreset).not.toHaveBeenCalled()
  expect(hydrateSeedance25IdentityPreset).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: /^Повторить/ })).not.toBeInTheDocument()
})
test.each(cases)('%s %s legacy repeat cannot silently replace an unavailable model', async (surface, kind) => {
  const app = await mount(surface, kind, false)
  expect(await screen.findByText(/Модель исходной работы недоступна/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Повторить/ })).not.toBeInTheDocument()
  expect(app.setActiveTab).not.toHaveBeenCalled()
  expect(app.setPromptPreset).not.toHaveBeenCalled()
  expect(app.setVideoPromptPreset).not.toHaveBeenCalled()
  expect(hydrateSeedance25IdentityPreset).not.toHaveBeenCalled()
})
test.each(cases)('%s %s legacy available model still opens its own generator', async (surface, kind) => {
  const model = kind === 'image' ? 'banana_pro' : 'seedance_2_5'
  const app = await mount(surface, kind, false, model)
  const setter = kind === 'image' ? app.setPromptPreset : app.setVideoPromptPreset
  await waitFor(() => expect(setter).toHaveBeenCalledWith(expect.objectContaining({ model, sourceFeedGenId: 42 })))
  expect(app.setActiveTab).toHaveBeenCalledWith(kind === 'image' ? 1 : 2)
  expect(app.openSmartRepeat).not.toHaveBeenCalled()
})
