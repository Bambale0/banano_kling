import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { ProfileTab } from '@/components/tabs/profile-tab'
import { useApp } from '@/lib/app-context'
import { fetchPartnerOverview, fetchProfileFeed, fetchTaskDetail } from '@/lib/api'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({
  addFeedComment: jest.fn(), fetchFeedComments: jest.fn(), fetchMyFeed: jest.fn(),
  fetchPartnerOverview: jest.fn(), fetchProfileFeed: jest.fn(), fetchTaskDetail: jest.fn(),
  likeFeedItem: jest.fn(), saveProfileChannel: jest.fn(),
  setFeedItemBlurred: jest.fn(), shareFeedItem: jest.fn(),
}))

const sourceResult = {
  id: 165, task_id: 'tg-published-image-165', model: 'banana_pro',
  gen_type: 'image' as const,
  result_url: 'https://example.test/published.png', preview_url: 'https://example.test/published.png',
  result_urls: ['https://example.test/published.png'], prompt: '',
  likes_count: 0, shares_count: 0, comments_count: 0,
  aspect_ratio: '1:1', reference_images: [], reference_videos: [], author: 'Owner',
  is_mine: true, remixes: 0, score: 0, created_at: '2026-10-14',
  prompt_hidden: true, prompt_actions_allowed: false,
  publication_scope: 'feed' as const, feed_interactions_enabled: true,
}
const ownerTask = {
  task_id: sourceResult.task_id, type: 'image', status: 'completed',
  result_url: sourceResult.result_url, is_public_feed: true, prompt_hidden: true,
  prompt_actions_allowed: false, prompt: '', publication_scope: 'feed',
}

function setup(foreign = false) {
  const selectTask = jest.fn()
  ;(useApp as jest.Mock).mockReturnValue({
    state: {
      mode: 'live',
      user: { firstName: 'Owner', username: 'owner', referralCode: 'OWN', credits: 100 },
      recentTasks: [], imageModels: [], videoModels: [],
    },
    viewedProfileCode: foreign ? 'FOREIGN' : null,
    feedDeepLink: null, consumeFeedDeepLink: jest.fn(), setActiveTab: jest.fn(),
    selectTask, setPromptPreset: jest.fn(), setVideoPromptPreset: jest.fn(),
  } as unknown as ReturnType<typeof useApp>)
  ;(fetchProfileFeed as jest.Mock).mockResolvedValue({
    feed: [{ ...sourceResult, is_mine: !foreign }],
    profile: { display_name: foreign ? 'Other' : 'Owner', posts_count: 1, likes_count: 0, shares_count: 0, remixes_count: 0 },
  })
  ;(fetchPartnerOverview as jest.Mock).mockResolvedValue({
    prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0,
  })
  ;(fetchTaskDetail as jest.Mock).mockResolvedValue(ownerTask)
  return { selectTask }
}

beforeEach(() => jest.clearAllMocks())

it('opens authenticated editor for a Telegram-published work in own profile', async () => {
  const { selectTask } = setup()
  render(<ProfileTab />)
  fireEvent.click(await screen.findByRole('button', { name: 'Открыть публикацию' }))
  fireEvent.click(screen.getByRole('button', { name: 'Настроить публикацию' }))
  await waitFor(() => expect(fetchTaskDetail).toHaveBeenCalledWith(sourceResult.task_id))
  expect(selectTask).toHaveBeenCalledWith(ownerTask)
})

it('never offers publication editing from another person profile', async () => {
  const { selectTask } = setup(true)
  render(<ProfileTab />)
  fireEvent.click(await screen.findByRole('button', { name: 'Открыть публикацию' }))
  expect(screen.queryByRole('button', { name: 'Настроить публикацию' })).not.toBeInTheDocument()
  expect(fetchTaskDetail).not.toHaveBeenCalled()
  expect(selectTask).not.toHaveBeenCalled()
})
