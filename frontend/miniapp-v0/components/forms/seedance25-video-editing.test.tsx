import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Seedance25PublicForm } from './seedance25-public-form'
import { Seedance25AdminForm } from './seedance25-admin-form'
import { generateSeedance25, quoteSeedance25Identity } from '@/lib/seedance25-api'

jest.mock('@/lib/seedance25-api', () => ({
  ...jest.requireActual('@/lib/seedance25-api'),
  quoteSeedance25Identity: jest.fn(),
  SEEDANCE25_MAX_PROMPT_LENGTH: 30000,
  SEEDANCE25_IDENTITY_MAX_PROMPT_LENGTH: 20480,
  generateSeedance25: jest.fn().mockResolvedValue({ ok: true, task_id: 'editing-task', duration: -1, aspect_ratio: 'adaptive', admin_free: true }),
  uploadSeedance25Video: jest.fn(),
}))
jest.mock('@/lib/api', () => ({ uploadFile: jest.fn(), getInitData: () => 'user=%7B%22id%22%3A1%7D' }))
beforeEach(() => {
  jest.clearAllMocks(); localStorage.clear()
  ;(quoteSeedance25Identity as jest.Mock).mockImplementation(async payload => {
    if (payload.videoEditing && payload.referenceVideos.length !== 1) throw new Error('Добавьте ровно одно исходное видео')
    const input = 7
    const output = payload.videoEditing ? input : payload.duration
    return { quote_id: 'a'.repeat(32), quote_hash: 'b'.repeat(64), cost: (input + output) * 4,
      charge_cost: (input + output) * 4, input_seconds: input, selected_output_seconds: output }
  })
})

it('sends editing settings, locks controls, and restores generation choices', async () => {
  render(<Seedance25PublicForm credits={1000} isAdmin />)
  fireEvent.change(screen.getByLabelText('Длительность видео'), { target: { value: '12' } })
  fireEvent.click(screen.getByRole('button', { name: '16:9' }))
  fireEvent.change(screen.getByLabelText(/Видео — по одному/), { target: { value: 'https://example.com/source.mp4' } })
  fireEvent.click(screen.getByLabelText('Редактировать видео'))
  expect(screen.getByLabelText('Длительность видео')).toBeDisabled()
  expect(screen.getByRole('button', { name: '16:9' })).toBeDisabled()
  expect(screen.getByText(/4–30 секунд/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Промпт для Seedance 2.5'), { target: { value: 'Replace the background' } })
  fireEvent.click(await screen.findByRole('button', { name: /Создать видео/ }))
  await waitFor(() => expect(generateSeedance25).toHaveBeenCalledWith(expect.objectContaining({ videoEditing: true, duration: -1, ratio: 'adaptive' })))
  fireEvent.click(screen.getByLabelText('Редактировать видео'))
  expect(screen.getByLabelText('Длительность видео')).toHaveValue('12')
  expect(screen.getByLabelText('Длительность видео')).toBeEnabled()
})
it('requires exactly one source video in editing mode', async () => {
  render(<Seedance25PublicForm credits={1000} isAdmin />)
  fireEvent.click(screen.getByLabelText('Редактировать видео'))
  fireEvent.change(screen.getByLabelText(/Видео — по одному/), { target: { value: 'https://example.com/a.mp4\nhttps://example.com/b.mp4' } })
  expect(await screen.findByText(/ровно одно исходное видео/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Не удалось рассчитать стоимость/ })).toBeDisabled()
  expect(generateSeedance25).not.toHaveBeenCalled()
})
it('keeps editing unavailable to billed users', () => {
  render(<Seedance25PublicForm credits={1000} isAdmin={false} />)
  expect(screen.queryByLabelText('Редактировать видео')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Длительность видео')).toBeEnabled()
})

it('preserves fixed duration for ordinary public reference generation', async () => {
  render(<Seedance25PublicForm credits={1000} isAdmin={false} />)
  fireEvent.change(screen.getByLabelText('Длительность видео'), { target: { value: '12' } })
  fireEvent.click(screen.getByRole('button', { name: '16:9' }))
  fireEvent.change(screen.getByLabelText(/Видео — по одному/), { target: { value: 'https://example.com/source.mp4' } })
  fireEvent.click(await screen.findByRole('button', { name: /Создать видео/ }))
  await waitFor(() => expect(generateSeedance25).toHaveBeenCalledWith(expect.objectContaining({ videoEditing: false, duration: 12, ratio: '16:9' })))
})


it('uses the same editing contract from the legacy admin form', async () => {
  const { container } = render(<Seedance25AdminForm />)
  fireEvent.click(screen.getByRole('button', { name: /Мультимодально/ }))
  fireEvent.click(screen.getByLabelText('Редактировать видео'))
  fireEvent.change(screen.getByPlaceholderText(/video refs/), { target: { value: 'asset://source-video' } })
  expect(container.querySelector('input[type="range"]')).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /Запустить Seedance/ }))
  await waitFor(() => expect(generateSeedance25).toHaveBeenCalledWith(expect.objectContaining({ videoEditing: true, duration: -1, ratio: 'adaptive', referenceVideos: ['asset://source-video'] })))
})

it('quotes source-locked editing and preserves the remembered fixed duration', async () => {
  const model = { id: 'seedance_2_5', quality_costs: { '720p': 4 } } as any
  render(<Seedance25PublicForm model={model} credits={1000} isAdmin />)
  fireEvent.change(screen.getByLabelText('Длительность видео'), { target: { value: '12' } })
  fireEvent.change(screen.getByLabelText(/Видео — по одному/), { target: { value: 'https://example.com/source.mp4' } })
  await screen.findByText('76🍌')
  expect(generateSeedance25).not.toHaveBeenCalled()
  fireEvent.click(screen.getByLabelText('Редактировать видео'))
  await screen.findByText('56🍌')
  fireEvent.click(screen.getByLabelText('Редактировать видео'))
  await screen.findByText('76🍌')
  expect(screen.getByLabelText('Длительность видео')).toHaveValue('12')
  expect(generateSeedance25).not.toHaveBeenCalled()
})

it('quotes video-reference multiplier in the legacy admin editing form', () => {
  const model = { id: 'seedance_2_5', quality_costs: { '720p': 4 } } as any
  const { container } = render(<Seedance25AdminForm model={model} />)
  fireEvent.click(screen.getByRole('button', { name: /Мультимодально/ }))
  fireEvent.change(container.querySelector('input[type="range"]')!, { target: { value: '12' } })
  fireEvent.change(screen.getByPlaceholderText(/video refs/), { target: { value: 'asset://source-video' } })
  expect(screen.getByText('96🍌')).toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('Редактировать видео'))
  expect(screen.getByText('40🍌')).toBeInTheDocument()
})

it('uses authenticated measured creator totals without a client multiplier', async () => {
  ;(quoteSeedance25Identity as jest.Mock).mockResolvedValue({ quote_id: 'a'.repeat(32), quote_hash: 'b'.repeat(64), cost: 15, charge_cost: 15, input_seconds: 7, selected_output_seconds: 5 })
  const model = {
    id: 'seedance_2_5', quality_costs: { '720p': 1.25 },
    quality_duration_costs: { '720p': { '5': 6 } },
  } as any
  render(<Seedance25PublicForm model={model} credits={12} isAdmin={false} />)
  fireEvent.change(screen.getByLabelText('Длительность видео'), { target: { value: '5' } })
  fireEvent.change(screen.getByLabelText(/Видео — по одному/), { target: { value: 'https://example.com/source.mp4' } })
  expect(await screen.findByText('15🍌')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Не хватает 3/ })).toBeDisabled()
  expect(screen.queryByLabelText('Редактировать видео')).not.toBeInTheDocument()
})
