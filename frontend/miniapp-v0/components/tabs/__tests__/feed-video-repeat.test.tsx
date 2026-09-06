import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { FeedTab } from '@/components/tabs/feed-tab'
import { useApp } from '@/lib/app-context'
import { fetchFeed, repeatFeedVideo } from '@/lib/api'

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
  prompt: null,
  likes_count: 0,
  shares_count: 0,
  comments_count: 0,
  aspect_ratio: '9:16',
  duration: 12,
  scenario: 'video' as const,
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
  it('opens the source-aware video form instead of launching immediately', async () => {
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
        scenario: 'video',
        ratio: '9:16',
        duration: 12,
        sourceFeedGenId: 42,
        promptHidden: true,
      }))
    })
    expect(setActiveTab).toHaveBeenCalledWith(2)
    expect(mockedRepeatFeedVideo).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /Настроить/i })).not.toBeInTheDocument()
  })
})
