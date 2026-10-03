import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'

import { TrendsTab } from '@/components/tabs/trends-tab'
import { useApp } from '@/lib/app-context'
import { fetchPrompts } from '@/lib/api'
import type { PromptItem } from '@/lib/types'
import { genjutsuCall } from '@/lib/genjutsu-api'

jest.mock('@/lib/app-context', () => ({
  useApp: jest.fn(),
}))

jest.mock('@/lib/api', () => ({
  fetchPrompts: jest.fn(),
  fetchPromptLink: jest.fn(),
  deactivatePrompt: jest.fn(),
  submitPrompt: jest.fn(),
  uploadFile: jest.fn(),
}))

jest.mock('@/lib/trend-admin-api', () => ({
  updateTrendPreview: jest.fn(),
}))

jest.mock('@/lib/genjutsu-api', () => ({
  genjutsuCall: jest.fn(),
  openGenjutsu: jest.fn(),
}))

jest.mock('@/components/trend-runner-dialog', () => ({
  TrendRunnerDialog: () => null,
}))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>
const mockedFetchPrompts = fetchPrompts as jest.MockedFunction<typeof fetchPrompts>
const mockedGenjutsuCall = genjutsuCall as jest.MockedFunction<typeof genjutsuCall>

const trend: PromptItem = {
  id: 1606,
  title: 'Фото для видео тренда',
  description: 'Фото-шаблон',
  prompt_text: '',
  category: 'photo',
  tags: ['trend'],
  uses_count: 0,
  likes: 0,
  repeat_cost: 1.5,
  preview_url: null,
  model: 'banana_pro',
  author_id: 1,
  status: 'approved',
  generation_settings: {
    kind: 'image',
    user_input: 'photo',
    model: 'banana_pro',
    ratio: '1:1',
    quality: '2K',
    count: 1,
  },
}

describe('TrendsTab repeat pricing', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    mockedUseApp.mockReturnValue({
      state: {
        mode: 'live',
        user: { isAdmin: false },
        imageModels: [
          {
            id: 'banana_pro',
            label: 'Nano Banana Pro',
            description: '',
            cost: 1.5,
            ratios: ['1:1'],
            requires_reference: false,
            max_references: 14,
          },
        ],
        videoModels: [],
      },
      trendToRun: null,
      setTrendToRun: jest.fn(),
    } as unknown as ReturnType<typeof useApp>)
    mockedFetchPrompts.mockResolvedValue([trend])
  })

  it('shows the backend-provided repeat price on the trend card', async () => {
    render(<TrendsTab />)

    expect(
      await screen.findByRole('button', { name: 'Повторить · 1.5🍌' }),
    ).toBeInTheDocument()
  })
})


it('loads the live Genjutsu recipe price for trend cards', async () => {
  const recipeId = 'a'.repeat(32)
  mockedFetchPrompts.mockResolvedValue([{
    ...trend,
    id: 1707,
    title: 'Genjutsu trend',
    category: 'video',
    tags: ['trend', 'trend-video'],
    model: 'genjutsu',
    repeat_cost: null,
    generation_settings: {
      kind: 'video', user_input: 'photo', model: 'genjutsu', ratio: '16:9',
      genjutsu_recipe_id: recipeId,
    },
  }])
  mockedGenjutsuCall.mockResolvedValue({ costs: { [recipeId]: 27 } } as never)

  render(<TrendsTab />)

  expect(await screen.findByRole('button', { name: 'Повторить · 27🍌' })).toBeInTheDocument()
  expect(mockedGenjutsuCall).toHaveBeenCalledWith('recipe_costs', { recipe_ids: [recipeId] })
})
