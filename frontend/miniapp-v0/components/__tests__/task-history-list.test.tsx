import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { TaskHistoryList } from '../task-history-list'
import { useApp } from '@/lib/app-context'
import { fetchTaskHistory } from '@/lib/api'
import type { Task } from '@/lib/types'

jest.mock('lucide-react', () => { const icons = jest.requireActual('lucide-react'); return { ...icons, CheckCircle2: icons.Check, XCircle: icons.X } })
jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({ fetchTaskHistory: jest.fn() }))
const selectTask = jest.fn()
const history = fetchTaskHistory as jest.Mock
const task = (index: number): Task => ({ feed_id: index, task_id: `task-${index}`, type: 'video', model: 'wan_3', model_label: 'Wan', aspect_ratio: '9:16', status: 'completed', created_at: '2026-10-21T10:00:00Z', prompt_preview: `Video ${index}`, cost: 1 })
let state: any
let taskDetail: any
beforeEach(() => {
  jest.clearAllMocks()
  taskDetail = null
  state = { mode: 'live', user: { telegramId: 101 }, recentTasks: Array.from({ length: 8 }, (_, i) => task(20 - i)) }
  ;(useApp as jest.Mock).mockImplementation(() => ({ state, selectTask, taskDetail }))
})

test('loads and opens an older published video beyond the eight bootstrap cards', async () => {
  history.mockResolvedValue({ recent_tasks: [task(12), task(11)], next_cursor: null })
  render(<TaskHistoryList />)
  fireEvent.click(screen.getByRole('button', { name: 'Загрузить ещё' }))
  fireEvent.click(await screen.findByRole('button', { name: /Video 11/ }))
  expect(selectTask).toHaveBeenCalledWith(task(11))
  expect(history).toHaveBeenCalledWith('task-13', expect.any(AbortSignal))
  expect(screen.queryByRole('button', { name: 'Загрузить ещё' })).not.toBeInTheDocument()
})

test('refresh keeps previously visible pages and never duplicates tasks', async () => {
  history.mockResolvedValue({ recent_tasks: [task(12), task(11)], next_cursor: 'task-11' })
  const view = render(<TaskHistoryList />)
  fireEvent.click(screen.getByRole('button', { name: 'Загрузить ещё' }))
  await screen.findByText('Video 11')
  state = { ...state, recentTasks: [task(21), ...state.recentTasks.slice(0, 7)] }
  view.rerender(<TaskHistoryList />)
  expect(screen.getByText('Video 13')).toBeInTheDocument()
  expect(screen.getAllByText('Video 12')).toHaveLength(1)
  expect(screen.getByText('Video 21')).toBeInTheDocument()
})

test('an older pending card follows its confirmed detail status and publication edits after closing', async () => {
  history.mockResolvedValue({ recent_tasks: [{ ...task(12), status: 'pending' }], next_cursor: null })
  const view = render(<TaskHistoryList />)
  fireEvent.click(screen.getByRole('button', { name: 'Загрузить ещё' }))
  expect(await screen.findByRole('button', { name: /Video 12.*В обработке/ })).toBeInTheDocument()
  taskDetail = { ...task(12), is_public_feed: true }
  view.rerender(<TaskHistoryList />)
  expect(screen.getByRole('button', { name: /Video 12.*Готово/ })).toBeInTheDocument()
  taskDetail = null
  view.rerender(<TaskHistoryList />)
  fireEvent.click(screen.getByRole('button', { name: /Video 12/ }))
  expect(selectTask).toHaveBeenCalledWith(expect.objectContaining({ status: 'completed', is_public_feed: true }))
})

test('failed page is retryable and raw errors are hidden', async () => {
  history.mockRejectedValueOnce(new Error('private auth token')).mockResolvedValueOnce({ recent_tasks: [task(12)], next_cursor: null })
  render(<TaskHistoryList />)
  fireEvent.click(screen.getByRole('button', { name: 'Загрузить ещё' }))
  await screen.findByRole('alert')
  expect(screen.queryByText(/private auth token/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Загрузить ещё' }))
  await screen.findByText('Video 12')
  expect(history.mock.calls.map(call => call[0])).toEqual(['task-13', 'task-13'])
})

test('account switch aborts a pending page and discards its late results', async () => {
  let finish!: (value: unknown) => void
  history.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const view = render(<TaskHistoryList />)
  fireEvent.click(screen.getByRole('button', { name: 'Загрузить ещё' }))
  await waitFor(() => expect(history).toHaveBeenCalledTimes(1))
  const signal = history.mock.calls[0][1] as AbortSignal
  state = { ...state, user: { telegramId: 202 }, recentTasks: [task(99)] }
  view.rerender(<TaskHistoryList />)
  expect(signal.aborted).toBe(true)
  await act(async () => finish({ recent_tasks: [task(12)], next_cursor: null }))
  expect(screen.queryByText('Video 12')).not.toBeInTheDocument()
  expect(screen.queryByText('Video 20')).not.toBeInTheDocument()
  expect(screen.getByText('Video 99')).toBeInTheDocument()
})
