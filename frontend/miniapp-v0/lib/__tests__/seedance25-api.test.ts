import { generateSeedance25, type Seedance25GeneratePayload } from '../seedance25-api'

jest.mock('../api', () => ({ getApiBasePath: () => '/api', getInitData: () => 'signed-data', getStartParamFallback: () => '', uploadFile: jest.fn() }))
const payload: Seedance25GeneratePayload = {
  scenario: 'multimodal', prompt: 'Edit the background', ratio: '16:9', duration: 12,
  resolution: '720p', outputFormat: 'mp4', generateAudio: true, returnLastFrame: false,
  webSearch: false, nsfwChecker: false, referenceVideos: ['https://example.com/source.mp4'],
}

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({ ok: true, text: async () => JSON.stringify({ ok: true, status: 'queued' }) })
})

it.each([true, false])('transports editing=%s without overwriting reference generation parameters', async (videoEditing) => {
  await generateSeedance25({ ...payload, videoEditing })
  const body = JSON.parse((fetch as jest.Mock).mock.calls[0][1].body)
  expect(body.seedance25_video_editing).toBe(videoEditing)
  expect(body.v_duration).toBe(videoEditing ? -1 : 12)
  expect(body.v_ratio).toBe(videoEditing ? 'adaptive' : '16:9')
  expect(body.v_reference_videos).toEqual(payload.referenceVideos)
})
