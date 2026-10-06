import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { GenjutsuFeedPublisher } from '../genjutsu-feed-publisher'
import { GenjutsuError, genjutsuCall, type Run } from '@/lib/genjutsu-api'
import { notifyFeedChanged } from '@/lib/feed-events'

jest.mock('@/lib/genjutsu-api', () => ({ ...jest.requireActual('@/lib/genjutsu-api'), genjutsuCall: jest.fn() }))
jest.mock('@/lib/feed-events', () => ({ notifyFeedChanged: jest.fn() }))
const call = genjutsuCall as jest.Mock
const run: Run = {
  id: 'run', state: 'completed', private_recipe: 0, admin_free: 0, cancel_requested: 0, created_ms: 0, credits: 0,
  plan: { source_asset_id: 'hidden-source', variants: 1, continuation: 'automatic', steps: [{
    operation: 'motion_transfer', resolution: '720p', prompt: 'secret prompt', preserve: '', preset_id: null,
    references: [{ asset_id: 'private-face', role: 'character', label: 'Герой', binding: 'user' },
      { asset_id: 'fixed-outfit', role: 'wardrobe', label: 'Одежда', binding: 'fixed' }],
  }] },
  steps: [{ id: 'output', variant: 0, ordinal: 0, status: 'completed',
    spec: { operation: 'motion_transfer', resolution: '720p' }, reserved_credits: 0, actual_credits: 0,
    refunded_credits: 0, error_code: null, delivery_status: null, delivery_error: null,
    output_asset: { id: 'result', kind: 'video', url: 'https://example.test/result.mp4' },
  }],
}
beforeEach(() => jest.clearAllMocks())

test('owner publishes a final output with explicit replacement policy and immutable photo roles', async () => {
  const card = { id: 21, genjutsu_recipe_id: 'recipe' }
  call.mockResolvedValue({ card, recipe: { id: 'recipe' } })
  render(<GenjutsuFeedPublisher run={run} step={run.steps[0]} />)
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать в ленту' }))
  expect(screen.getByText('Герой: своё фото при повторе')).toBeInTheDocument()
  expect(screen.getByText('Одежда: скрытый закреплённый референс')).toBeInTheDocument()
  expect(screen.queryByText('secret prompt')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Название публикации'), { target: { value: 'Мой танец' } })
  fireEvent.change(screen.getByLabelText('Видео при повторе'), { target: { value: 'fixed' } })
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать результат' }))
  await screen.findByText('Опубликовано в ленте')
  expect(call).toHaveBeenCalledTimes(1)
  expect(call).toHaveBeenCalledWith('feed_publish', { run_id: 'run', step_id: 'output', title: 'Мой танец', source_binding: 'fixed' })
  expect(notifyFeedChanged).toHaveBeenCalledWith(card)
})

test.each([
  ['private', { ...run, private_recipe: 1 }],
  ['incomplete', { ...run, state: 'running' }],
  ['redacted', { ...run, plan: undefined }],
  ['intermediate', { ...run, steps: [...run.steps, { ...run.steps[0], id: 'next', ordinal: 1 }] }],
])('does not offer publication of a %s result', (_label, value) => {
  render(<GenjutsuFeedPublisher run={value} step={value.steps[0]} />)
  expect(screen.queryByRole('button', { name: 'Опубликовать в ленту' })).not.toBeInTheDocument()
})

test('cancel does not publish and retry after a lost response preserves exactly one declaration', async () => {
  call.mockRejectedValueOnce(new Error('Ответ потерян')).mockResolvedValue({ card: { id: 22 }, recipe: { id: 'recipe' } })
  render(<GenjutsuFeedPublisher run={run} step={run.steps[0]} />)
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать в ленту' }))
  fireEvent.click(screen.getByRole('button', { name: 'Отмена' }))
  expect(call).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать в ленту' }))
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать результат' }))
  await screen.findByText('Ответ потерян')
  expect(screen.getByLabelText('Видео при повторе')).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Повторить публикацию' }))
  await waitFor(() => expect(call).toHaveBeenCalledTimes(2))
  expect(call.mock.calls[0]).toEqual(call.mock.calls[1])
  await screen.findByText('Опубликовано в ленте')
})

test('rapid duplicate clicks send only one publication request and display its result', async () => {
  let finish!: (value: unknown) => void
  call.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  render(<GenjutsuFeedPublisher run={run} step={run.steps[0]} />)
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать в ленту' }))
  const publish = screen.getByRole('button', { name: 'Опубликовать результат' })
  fireEvent.click(publish)
  fireEvent.click(publish)
  expect(call).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Публикуем…' })).toBeDisabled()
  finish({ card: { id: 23 } })
  await screen.findByText('Опубликовано в ленте')
})

test('an earlier output cannot publish when the final planned step is missing', () => {
  const value = { ...run, plan: { ...run.plan!, steps: [...run.plan!.steps, run.plan!.steps[0]] } }
  render(<GenjutsuFeedPublisher run={value} step={value.steps[0]} />)
  expect(screen.queryByRole('button', { name: 'Опубликовать в ленту' })).not.toBeInTheDocument()
})

test('withdrawn publication is permanent and does not offer a misleading retry', async () => {
  call.mockRejectedValue(new GenjutsuError('feed_publication_withdrawn', 'Публикация была удалена', 409))
  render(<GenjutsuFeedPublisher run={run} step={run.steps[0]} />)
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать в ленту' }))
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать результат' }))
  await screen.findByText('Публикация была удалена')
  expect(screen.getByRole('button', { name: 'Публикация недоступна' })).toBeDisabled()
  expect(screen.queryByText(/Повторная попытка сохранит/)).not.toBeInTheDocument()
})

test('late success from an unmounted result does not mark another result published', async () => {
  let finish!: (value: unknown) => void
  call.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const view = render(<GenjutsuFeedPublisher key="run:output" run={run} step={run.steps[0]} />)
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать в ленту' }))
  fireEvent.click(screen.getByRole('button', { name: 'Опубликовать результат' }))
  const next = { ...run, id: 'other-run' }
  view.rerender(<GenjutsuFeedPublisher key="other-run:output" run={next} step={next.steps[0]} />)
  finish({ card: { id: 24 } })
  await waitFor(() => expect(notifyFeedChanged).toHaveBeenCalledWith({ id: 24 }))
  expect(screen.getByRole('button', { name: 'Опубликовать в ленту' })).toBeInTheDocument()
  expect(screen.queryByText('Опубликовано в ленте')).not.toBeInTheDocument()
})
