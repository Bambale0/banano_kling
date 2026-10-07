import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { FeedTab } from '@/components/tabs/feed-tab'
import { useApp } from '@/lib/app-context'
import { fetchFeed, repeatFeedVideo } from '@/lib/api'
import { openGenjutsu } from '@/lib/genjutsu-api'

jest.mock('@/lib/genjutsu-api', () => ({ openGenjutsu: jest.fn() }))
jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({
  addFeedComment: jest.fn(),
  fetchFeed: jest.fn(),
  fetchFeedComments: jest.fn(),
  likeFeedItem: jest.fn(),
  removeFeedItem: jest.fn(),
  repeatFeedVideo: jest.fn(),
  setFeedItemBlurred: jest.fn(),
  shareFeedItem: jest.fn(),
}))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>
const mockedFetchFeed = fetchFeed as jest.MockedFunction<typeof fetchFeed>
const mockedRepeatFeedVideo = repeatFeedVideo as jest.MockedFunction<typeof repeatFeedVideo>

const videoItem = {
  id: 42,
  task_id: 'source-task',
  model: 'seedance_2_5',
  gen_type: 'video' as const,
  result_url: 'https://example.test/source.mp4',
  preview_url: 'https://example.test/source.mp4',
  result_urls: ['https://example.test/source.mp4'],
  prompt: 'SYNTHETIC_PRIVATE_FEED_RECIPE',
  likes_count: 0,
  shares_count: 0,
  comments_count: 0,
  aspect_ratio: '9:16',
  duration: 12,
  scenario: 'imgtxt' as const,
  reference_images: [],
  reference_videos: [],
  references_hidden: true,
  author: 'Автор',
  is_mine: false,
  remixes: 0,
  score: 0,
  created_at: '2026-09-06T00:00:00Z',
  prompt_hidden: true,
  prompt_actions_allowed: false,
  feed_references_visible: false,
}

describe('FeedTab editable video repeat', () => {
  beforeEach(() => jest.clearAllMocks())
  it('opens hidden image-only Seedance repeats in photo + text mode', async () => {
    const setActiveTab = jest.fn()
    const setVideoPromptPreset = jest.fn()

    mockedUseApp.mockReturnValue({
      state: {
        mode: 'live',
        user: { credits: 100, isAdmin: false },
        imageModels: [],
        videoModels: [{
          id: 'seedance_2_5',
          label: 'Seedance 2.5',
          description: 'video',
          durations: [12],
          ratios: ['9:16'],
          supports: ['text', 'imgtxt', 'video'],
          costs: { '12': 12 },
        }],
        recentTasks: [],
        savedReferences: [],
        paymentPackages: [],
        lastSync: new Date(),
      },
      feedDeepLink: null,
      consumeFeedDeepLink: jest.fn(),
      setActiveTab,
      setPromptPreset: jest.fn(),
      setVideoPromptPreset,
      openProfile: jest.fn(),
    } as unknown as ReturnType<typeof useApp>)

    mockedFetchFeed.mockResolvedValue({
      feed: [videoItem],
      models: [{ id: 'seedance_2_5', label: 'Seedance 2.5' }],
    } as Awaited<ReturnType<typeof fetchFeed>>)

    render(<FeedTab />)

    await screen.findByRole('button', { name: 'Открыть видео' })
    fireEvent.click(screen.getByRole('button', { name: 'Открыть видео' }))
    fireEvent.click(await screen.findByRole('button', { name: /^Повторить$/i }))

    await waitFor(() => {
      expect(setVideoPromptPreset).toHaveBeenCalledWith(expect.objectContaining({
        title: 'Повторить видео из ленты',
        model: 'seedance_2_5',
        scenario: 'imgtxt',
        ratio: '9:16',
        duration: 12,
        sourceFeedGenId: 42,
        promptHidden: true,
        prompt: '',
      }))
    })
    expect(setActiveTab).toHaveBeenCalledWith(2)
    expect(mockedRepeatFeedVideo).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /Настроить/i })).not.toBeInTheDocument()
  })
  it('opens opaque Genjutsu recipes without generic video fallback or generation', async () => {
    const setActiveTab = jest.fn()
    const setVideoPromptPreset = jest.fn()
    mockedUseApp.mockReturnValue({
      state: { mode: 'live', user: { credits: 100, isAdmin: false }, imageModels: [], videoModels: [] },
      feedDeepLink: null, consumeFeedDeepLink: jest.fn(), setActiveTab, setVideoPromptPreset,
      setPromptPreset: jest.fn(), openProfile: jest.fn(),
    } as unknown as ReturnType<typeof useApp>)
    mockedFetchFeed.mockResolvedValue({
      feed: [{ ...videoItem, model: 'genjutsu', genjutsu_recipe_id: 'recipe-id' }],
      models: [{ id: 'genjutsu', label: 'Higgsfield Genjutsu' }],
    } as Awaited<ReturnType<typeof fetchFeed>>)
    render(<FeedTab />)
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть видео' }))
    fireEvent.click(await screen.findByRole('button', { name: /^Повторить$/i }))
    expect(openGenjutsu).toHaveBeenCalledWith({ recipe_id: 'recipe-id' })
    expect(setVideoPromptPreset).not.toHaveBeenCalled()
    expect(setActiveTab).not.toHaveBeenCalled()
    expect(mockedRepeatFeedVideo).not.toHaveBeenCalled()
  })
  it('does not fall back to an unrelated model if Genjutsu linkage is missing', async () => {
    const setVideoPromptPreset = jest.fn()
    mockedUseApp.mockReturnValue({
      state: { mode: 'live', user: { credits: 100, isAdmin: false }, imageModels: [], videoModels: [] },
      feedDeepLink: null, consumeFeedDeepLink: jest.fn(), setActiveTab: jest.fn(), setVideoPromptPreset,
      setPromptPreset: jest.fn(), openProfile: jest.fn(),
    } as unknown as ReturnType<typeof useApp>)
    mockedFetchFeed.mockResolvedValue({
      feed: [{ ...videoItem, model: 'genjutsu', genjutsu_recipe_id: null }], models: [],
    } as Awaited<ReturnType<typeof fetchFeed>>)
    render(<FeedTab />)
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть видео' }))
    fireEvent.click(await screen.findByRole('button', { name: /^Повторить$/i }))
    expect(await screen.findByText('Повтор этой публикации недоступен. Обновите ленту.')).toBeInTheDocument()
    expect(openGenjutsu).not.toHaveBeenCalled()
    expect(setVideoPromptPreset).not.toHaveBeenCalled()
  })

})
