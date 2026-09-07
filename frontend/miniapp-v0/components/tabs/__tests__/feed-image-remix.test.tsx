import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { FeedTab } from '@/components/tabs/feed-tab'
import { useApp } from '@/lib/app-context'
import { fetchFeed } from '@/lib/api'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({
  addFeedComment: jest.fn(),
  fetchFeed: jest.fn(),
  fetchFeedComments: jest.fn(),
  likeFeedItem: jest.fn(),
  removeFeedItem: jest.fn(),
  setFeedItemBlurred: jest.fn(),
  shareFeedItem: jest.fn(),
}))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>
const mockedFetchFeed = fetchFeed as jest.MockedFunction<typeof fetchFeed>

const imageItem = {
  id: 55,
  task_id: 'source-image-task',
  model: 'banana_pro',
  gen_type: 'image' as const,
  result_url: 'https://example.test/source.png',
  preview_url: 'https://example.test/source.png',
  result_urls: ['https://example.test/source.png'],
  prompt: 'AUTHOR PROMPT MUST NOT BECOME EDITABLE',
  likes_count: 0,
  shares_count: 0,
  comments_count: 0,
  aspect_ratio: '1:1',
  duration: null,
  scenario: null,
  reference_images: [],
  reference_videos: [],
  references_hidden: true,
  author: 'Автор',
  is_mine: false,
  remixes: 0,
  score: 0,
  created_at: '2026-09-07T00:00:00Z',
  prompt_hidden: true,
  prompt_actions_allowed: false,
  feed_references_visible: false,
}

describe('FeedTab image remix prompt isolation', () => {
  it('opens the image form with an empty editable changes field while retaining source lineage', async () => {
    const setActiveTab = jest.fn()
    const setPromptPreset = jest.fn()

    mockedUseApp.mockReturnValue({
      state: {
        mode: 'live',
        user: { credits: 100, isAdmin: false },
        imageModels: [{
          id: 'banana_pro',
          label: 'Nano Banana Pro',
          description: 'image',
          cost: 2,
          ratios: ['1:1'],
          requires_reference: false,
          max_references: 4,
        }],
        videoModels: [],
        recentTasks: [],
        savedReferences: [],
        paymentPackages: [],
        lastSync: new Date(),
      },
      feedDeepLink: null,
      consumeFeedDeepLink: jest.fn(),
      setActiveTab,
      setPromptPreset,
      setVideoPromptPreset: jest.fn(),
      openProfile: jest.fn(),
    } as unknown as ReturnType<typeof useApp>)

    mockedFetchFeed.mockResolvedValue({
      feed: [imageItem],
      models: [{ id: 'banana_pro', label: 'Nano Banana Pro' }],
    } as Awaited<ReturnType<typeof fetchFeed>>)

    render(<FeedTab />)

    fireEvent.click(await screen.findByRole('button', { name: 'Открыть фото' }))
    fireEvent.click(await screen.findByRole('button', { name: /^Повторить$/i }))

    await waitFor(() => {
      expect(setPromptPreset).toHaveBeenCalledWith(expect.objectContaining({
        title: 'Повторить образ из ленты',
        prompt: '',
        model: 'banana_pro',
        ratio: '1:1',
        sourceFeedGenId: 55,
      }))
    })
    expect(setActiveTab).toHaveBeenCalledWith(1)
  })
})
