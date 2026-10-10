import '@testing-library/jest-dom'
import { fireEvent, render, screen, within } from '@testing-library/react'

import { ModelSelect } from './model-select'

const models = [
  { id: 'wan_3_prime', label: 'Wan 3.0 Video Prime', description: 'new', cost: 5 },
  { id: 'seedance_2_5', label: 'Seedance 2.5', description: 'video', cost: 3 },
  { id: 'grok_imagine', label: 'Grok Imagine', description: 'xai', cost: 2 },
  { id: 'v3_pro', label: 'Kling Pro', description: 'kling', cost: 4 },
  { id: 'future_video_model', label: 'Future Model', description: 'unknown', cost: 7 },
]

test('filters models by real groups and keeps unknown models in Russian other group', () => {
  const onChange = jest.fn()
  render(<ModelSelect models={models} value="wan_3_prime" onChange={onChange} />)

  fireEvent.click(screen.getByRole('button', { name: /Wan 3\.0 Video Prime/i }))
  fireEvent.click(screen.getByRole('button', { name: 'Grok' }))

  let popup = screen.getByTestId('model-select-menu')
  expect(within(popup).getByText('Grok Imagine')).toBeInTheDocument()
  expect(within(popup).queryByText('Wan 3.0 Video Prime')).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Другое' }))
  popup = screen.getByTestId('model-select-menu')
  expect(within(popup).getByText('Future Model')).toBeInTheDocument()
  expect(within(popup).queryByText('Grok Imagine')).not.toBeInTheDocument()
})

test('searches within selected family and can choose the selected model', () => {
  const onChange = jest.fn()
  render(<ModelSelect models={models} value="seedance_2_5" onChange={onChange} />)

  fireEvent.click(screen.getByRole('button', { name: /Seedance 2\.5/i }))
  fireEvent.click(screen.getByRole('button', { name: 'Все' }))
  fireEvent.change(screen.getByPlaceholderText('Поиск модели'), { target: { value: 'kling' } })
  fireEvent.click(screen.getByRole('button', { name: /Kling Pro/i }))

  expect(onChange).toHaveBeenCalledWith('v3_pro')
})

test('paginates long groups instead of rendering one uninterrupted list', () => {
  const many = Array.from({ length: 10 }, (_, index) => ({
    id: `seedance_extra_${index}`,
    label: `Seedance Extra ${index}`,
    description: 'bulk',
    cost: index,
  }))
  render(<ModelSelect models={[...models, ...many]} value="seedance_2_5" onChange={jest.fn()} />)

  fireEvent.click(screen.getByRole('button', { name: /Seedance 2\.5/i }))
  fireEvent.click(screen.getByRole('button', { name: 'Seedance' }))

  expect(screen.getByText('1/2')).toBeInTheDocument()
  const popup = screen.getByTestId('model-select-menu')
  expect(within(popup).queryByText('Seedance Extra 9')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Дальше' }))
  expect(screen.getByText('Seedance Extra 9')).toBeInTheDocument()
})
