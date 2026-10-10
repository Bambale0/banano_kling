import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MotionTab } from '../motion-tab'
import { useApp } from '@/lib/app-context'
import { generateMotion, quoteMotion, motionStatus, uploadFile, MiniAppApiError } from '@/lib/api'

jest.mock('lucide-react', () => ({ Sparkles: () => null, Upload: () => null, Video: () => null, Image: () => null, Wand2: () => null, CheckCircle2: () => null }))
jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({
  generateMotion: jest.fn(), quoteMotion: jest.fn(), motionStatus: jest.fn(), uploadFile: jest.fn(),
  MiniAppApiError: class extends Error { constructor(message: string, public code?: string) { super(message) } },
}))
jest.mock('../../result-card', () => ({ ResultCard: () => <div>Recovered result</div> }))

const key = 'motion-pending:5000000001'
const quote = { version: 2, billing_mode: 'source_locked_output', quote_hash: 'q1',
  input_seconds: 5, output_seconds: 5, billable_seconds: 10, rate_per_second: 1,
  cost: 10, charge_cost: 10, admin_free: false }
const task = { task_id: 'provider-a', type: 'video', model: 'motion_control_v26', status: 'pending' }
const addTask = jest.fn()
const context = {
  state: { mode: 'live', user: { telegramId: 5000000001, credits: 100, isAdmin: false },
    videoModels: [{ id: 'motion_control_v26', quality_costs: { '720p': 1, '1080p': 2 }, costs: {} }] },
  addTask, setCredits: jest.fn(), setTaskDetail: jest.fn(), selectTask: jest.fn(),
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
async function uploadBoth(view: ReturnType<typeof render>) {
  const inputs = view.container.querySelectorAll('input[type=file]')
  fireEvent.change(inputs[0], { target: { files: [new File(['photo'], 'photo.png', { type: 'image/png' })] } })
  fireEvent.change(inputs[1], { target: { files: [new File(['video'], 'video.mp4', { type: 'video/mp4' })] } })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Запустить Motion' })).toBeEnabled())
}
beforeEach(() => {
  jest.resetAllMocks()
  localStorage.clear()
  ;(useApp as jest.Mock).mockReturnValue(context)
  ;(quoteMotion as jest.Mock).mockResolvedValue(quote)
  ;(motionStatus as jest.Mock).mockImplementation(() => new Promise(() => {}))
  ;(uploadFile as jest.Mock).mockImplementation(async (kind, file) => ({
    id: file.name, name: file.name, url: 'https://example.test/' + file.name,
    type: kind === 'image_reference' ? 'image' : 'video', size: 5,
  }))
  let next = 0
  Object.defineProperty(global.crypto, 'randomUUID', { configurable: true,
    value: () => (++next).toString(16).padStart(32, '0') })
})

test('unmount/reload recovery then B survives late original response A', async () => {
  const originalA = deferred<unknown>()
  ;(generateMotion as jest.Mock).mockReturnValueOnce(originalA.promise)
    .mockImplementation(() => new Promise(() => {}))
  const first = render(<MotionTab />)
  await uploadBoth(first)
  fireEvent.click(screen.getByRole('button', { name: 'Запустить Motion' }))
  await waitFor(() => expect(generateMotion).toHaveBeenCalledTimes(1))
  const a = JSON.parse(localStorage.getItem(key)!).requestId
  first.unmount()

  ;(motionStatus as jest.Mock).mockResolvedValueOnce({ status: 'done', task: { ...task, status: 'completed' }, credits: 90 })
  const second = render(<MotionTab />)
  await waitFor(() => expect(localStorage.getItem(key)).toBeNull())
  expect(addTask).toHaveBeenCalledWith(expect.objectContaining({ status: 'completed' }))
  await uploadBoth(second)
  fireEvent.click(screen.getByRole('button', { name: 'Запустить Motion' }))
  await waitFor(() => expect(generateMotion).toHaveBeenCalledTimes(2))
  const b = JSON.parse(localStorage.getItem(key)!).requestId
  expect(b).not.toBe(a)
  await act(async () => originalA.resolve({ task, credits: 90 }))
  expect(JSON.parse(localStorage.getItem(key)!).requestId).toBe(b)
  expect(generateMotion).toHaveBeenCalledTimes(2)
})

test.each(['motion_quote_changed', 'motion_rejected'])('%s refreshes quote and requires another explicit launch', async (code) => {
  ;(generateMotion as jest.Mock).mockRejectedValueOnce(new MiniAppApiError('Проверьте цену', code))
    .mockImplementation(() => new Promise(() => {}))
  ;(quoteMotion as jest.Mock).mockResolvedValueOnce(quote).mockResolvedValue({ ...quote, quote_hash: 'q2', cost: 12 })
  const view = render(<MotionTab />)
  await uploadBoth(view)
  fireEvent.click(screen.getByRole('button', { name: 'Запустить Motion' }))
  await waitFor(() => expect(quoteMotion).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Запустить Motion' })).toBeEnabled())
  expect(generateMotion).toHaveBeenCalledTimes(1)
  expect(localStorage.getItem(key)).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Запустить Motion' }))
  await waitFor(() => expect(generateMotion).toHaveBeenCalledTimes(2))
  expect((generateMotion as jest.Mock).mock.calls[1][0].quoteHash).toBe('q2')
})

test('reload not-found recovery reuses original frozen payload and key', async () => {
  const payload = { requestId: 'a'.repeat(32), quoteHash: 'q-original', prompt: 'original',
    imageUrl: 'image', videoUrl: 'video', model: 'motion_control_v26', mode: '720p', direction: 'video' }
  localStorage.setItem(key, JSON.stringify({ requestId: payload.requestId, payload }))
  ;(motionStatus as jest.Mock).mockResolvedValueOnce({ status: 'not_found' })
  ;(generateMotion as jest.Mock).mockResolvedValueOnce({ task, credits: 90 })
  render(<MotionTab />)
  await waitFor(() => expect(generateMotion).toHaveBeenCalledWith(payload))
  await waitFor(() => expect(localStorage.getItem(key)).toBeNull())
  expect(quoteMotion).not.toHaveBeenCalled()
})
