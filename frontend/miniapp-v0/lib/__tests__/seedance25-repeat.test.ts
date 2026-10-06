import { fetchTaskDetail } from '../api'
import { hydrateSeedance25IdentityPreset } from '../seedance25-repeat'
import type { FeedItem, VideoPromptPreset } from '../types'

jest.mock('../api', () => ({ fetchTaskDetail: jest.fn() }))
const item = { id: 42, task_id: 'source', model: 'seedance_2_5', is_mine: true } as FeedItem
const preset: VideoPromptPreset = { title: 'Repeat', prompt: '', model: 'seedance_2_5', sourceFeedGenId: 42, promptHidden: true }
const detail = { prompt: 'User instruction', request_data: {
  seedance25_identity_transfer: true, resolution: '480p',
  reference_images: ['https://example.test/front.png', 'https://example.test/profile.png'],
  v_reference_videos: ['https://example.test/source.mp4'], seedance25_identity_quote: { cost: 1 },
} }
beforeEach(() => { jest.resetAllMocks(); (fetchTaskDetail as jest.Mock).mockResolvedValue(detail) })

it('hydrates owner identity repeat in order without restoring a stale quote', async () => {
  const result = await hydrateSeedance25IdentityPreset(item, preset)
  expect(fetchTaskDetail).toHaveBeenCalledWith('source')
  expect(result).toMatchObject({ sourceFeedGenId: 42, seedance25IdentityTransfer: true, seedance25Resolution: '480p', initialStartImage: [], promptHidden: true })
  expect(result.initialPhotoReferences?.map(file => file.url)).toEqual(detail.request_data.reference_images)
  expect(result.initialVideoReferences?.map(file => file.url)).toEqual(detail.request_data.v_reference_videos)
  expect(result).not.toHaveProperty('identityQuote')
})

it('does not read another owner private detail or change other models', async () => {
  expect(await hydrateSeedance25IdentityPreset({ ...item, is_mine: false }, preset)).toBe(preset)
  expect(await hydrateSeedance25IdentityPreset({ ...item, model: 'v3_pro' }, preset)).toBe(preset)
  expect(fetchTaskDetail).not.toHaveBeenCalled()
})

it('fails closed on denied owner detail instead of silently losing identity', async () => {
  ;(fetchTaskDetail as jest.Mock).mockRejectedValue(new Error('404 unavailable'))
  await expect(hydrateSeedance25IdentityPreset(item, preset)).rejects.toThrow('404 unavailable')
})

it('requires explicit boolean and leaves ordinary reference mode unchanged', async () => {
  ;(fetchTaskDetail as jest.Mock).mockResolvedValue({ request_data: { seedance25_identity_transfer: 'true' } })
  expect(await hydrateSeedance25IdentityPreset(item, preset)).toBe(preset)
})

it('leaves missing private inputs empty so identity asks for fresh uploads', async () => {
  ;(fetchTaskDetail as jest.Mock).mockResolvedValue({ request_data: { seedance25_identity_transfer: true } })
  const result = await hydrateSeedance25IdentityPreset(item, preset)
  expect(result.seedance25IdentityTransfer).toBe(true)
  expect(result.initialPhotoReferences).toEqual([])
  expect(result.initialVideoReferences).toEqual([])
})
