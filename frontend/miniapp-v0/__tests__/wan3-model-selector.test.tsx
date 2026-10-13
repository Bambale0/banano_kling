import '@testing-library/jest-dom'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { ModelSelect } from '@/components/forms/model-select'

const models = [
  { id: 'wan_3_prime', label: 'Wan 3.0 Video Prime', description: 'Видео, референсы и редактирование' },
  { id: 'wan_3', label: 'Wan 3.0 Video', description: 'Видео, референсы и редактирование' },
  { id: 'seedance_2_5', label: 'Seedance 2.5', description: 'Видео' },
  ...['gemini_omni', 'grok', 'kling_v1', 'kling_v2', 'v3', 'v26', 'veo3', 'veo3_fast', 'seedance_2'].map(id => ({ id, label: id, description: 'Видео' })),
]

function openSelector() {
  fireEvent.click(screen.getByRole('button', { expanded: false }))
  return within(screen.getByTestId('model-select-menu'))
}

test('ordinary WAN and Prime are separate adjacent choices on the first catalog page', () => {
  render(<ModelSelect models={models} value="wan_3_prime" onChange={jest.fn()} />)
  const menu = openSelector()
  const ordinary = menu.getByRole('button', { name: /^Wan 3\.0 Video Видео/ })
  const prime = menu.getByRole('button', { name: /^Wan 3\.0 Video Prime/ })
  expect(ordinary).toBeVisible()
  expect(prime).toBeVisible()
  expect(prime.nextElementSibling).toBe(ordinary)
  expect(menu.getByText('1/2')).toBeVisible()
  expect(ordinary).not.toHaveTextContent('NEW')
})

test.each(['wan_3', 'wan_3_prime'])('choosing %s preserves its exact model key', model => {
  const onChange = jest.fn()
  render(<ModelSelect models={models} value="kling_v1" onChange={onChange} />)
  const menu = openSelector()
  fireEvent.click(menu.getByRole('button', { name: model === 'wan_3' ? /^Wan 3\.0 Video Видео/ : /^Wan 3\.0 Video Prime/ }))
  expect(onChange).toHaveBeenCalledWith(model)
  expect(screen.queryByTestId('model-select-menu')).not.toBeInTheDocument()
})

test('WAN category and search keep both distinct choices reachable after pagination', () => {
  render(<ModelSelect models={models} value="kling_v1" onChange={jest.fn()} />)
  const menu = openSelector()
  fireEvent.click(menu.getByRole('button', { name: 'Дальше' }))
  fireEvent.click(menu.getByRole('button', { name: 'Wan', exact: true }))
  expect(menu.getByRole('button', { name: /^Wan 3\.0 Video Видео/ })).toBeVisible()
  expect(menu.getByRole('button', { name: /^Wan 3\.0 Video Prime/ })).toBeVisible()
  fireEvent.change(menu.getByLabelText('Поиск модели'), { target: { value: 'wan_3_prime' } })
  expect(menu.getByRole('button', { name: /^Wan 3\.0 Video Prime/ })).toBeVisible()
  expect(menu.queryByRole('button', { name: /^Wan 3\.0 Video Видео/ })).not.toBeInTheDocument()
})
