import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { TrendContentEditor } from '../trend-content-editor'
import { trendContent } from '@/lib/trend-admin-api'

jest.mock('@/lib/trend-admin-api', () => ({ trendContent: jest.fn() }))
const api = jest.mocked(trendContent)
const content = { id: 42, title: 'Старое название', prompt_text: 'Use @Image1 in garden', prompt_editable: true, revision: 'v1' }
beforeEach(() => { jest.clearAllMocks(); api.mockResolvedValue(content) })

test('loads private prompt, saves title and prompt without requiring preview upload', async () => {
  const onSaved = jest.fn().mockResolvedValue(undefined)
  render(<TrendContentEditor trendId={42} disabled={false} onSaved={onSaved} />)
  expect(await screen.findByDisplayValue(content.prompt_text)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Название тренда'), { target: { value: 'Новое название' } })
  fireEvent.change(screen.getByLabelText('Промпт тренда'), { target: { value: 'Use @Image1 on beach' } })
  api.mockResolvedValueOnce({ ...content, title: 'Новое название', prompt_text: 'Use @Image1 on beach', revision: 'v2' })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить название и промпт' }))
  await waitFor(() => expect(api).toHaveBeenLastCalledWith(42, { title: 'Новое название', prompt_text: 'Use @Image1 on beach', revision: 'v1' }))
  expect(await screen.findByText('Изменения сохранены')).toBeInTheDocument()
  expect(onSaved).toHaveBeenCalledWith('Новое название')
})

test('keeps edits visible when save fails', async () => {
  render(<TrendContentEditor trendId={42} disabled={false} onSaved={jest.fn()} />)
  await screen.findByDisplayValue(content.prompt_text)
  fireEvent.change(screen.getByLabelText('Название тренда'), { target: { value: 'Не потерять' } })
  api.mockRejectedValueOnce(new Error('Тренд уже изменён'))
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить название и промпт' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Тренд уже изменён')
  expect(screen.getByDisplayValue('Не потерять')).toBeInTheDocument()
})

test('a denied read never reveals text fields', async () => {
  api.mockRejectedValueOnce(new Error('Нет доступа'))
  render(<TrendContentEditor trendId={42} disabled={false} onSaved={jest.fn()} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Нет доступа')
  expect(screen.queryByLabelText('Промпт тренда')).not.toBeInTheDocument()
})
