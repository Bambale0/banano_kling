import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { RepeatPersonalizationFields } from './repeat-personalization-fields'
import { uploadFile } from '@/lib/api'
import type { TrendUserField } from '@/lib/types'
import { RepeatImageOptionsEditor } from '@/components/repeat-image-options-editor'

jest.mock('@/lib/api', () => ({ uploadFile: jest.fn() }))

const fields: TrendUserField[] = [{ key: 'outfit', label: 'Наряд девушки', type: 'text',
  image_choices: [{ id: 'dress', label: 'Платье', image_url: 'https://example.test/dress.jpg' },
    { id: 'suit', label: 'Костюм', image_url: 'https://example.test/suit.jpg' }], allow_custom_image: true }]

function Example() {
  const [values, setValues] = useState<Record<string, string>>({})
  return <><RepeatPersonalizationFields fields={fields} values={values} onChange={setValues} />
    <output>{JSON.stringify(values)}</output></>
}

test('image tiles select one option and custom upload replaces it with the server URL', async () => {
  ;(uploadFile as jest.Mock).mockResolvedValue({ url: 'https://example.test/own.jpg' })
  render(<Example />)
  expect(screen.getByAltText('Платье')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Платье' }))
  expect(screen.getByRole('button', { name: 'Платье' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Костюм' }))
  expect(screen.getByRole('button', { name: 'Платье' })).toHaveAttribute('aria-pressed', 'false')
  fireEvent.change(screen.getByLabelText('Свой вариант: Наряд девушки'), {
    target: { files: [new File(['photo'], 'own.jpg', { type: 'image/jpeg' })] },
  })
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('upload:https://example.test/own.jpg'))
  expect(uploadFile).toHaveBeenCalledWith('image_reference', expect.any(File))
})

test('failed uploads show an error and cannot leave a stale selected value', async () => {
  ;(uploadFile as jest.Mock).mockRejectedValue(new Error('Сбой загрузки'))
  render(<Example />)
  fireEvent.click(screen.getByRole('button', { name: 'Платье' }))
  fireEvent.change(screen.getByLabelText('Свой вариант: Наряд девушки'), {
    target: { files: [new File(['photo'], 'own.jpg', { type: 'image/jpeg' })] },
  })
  expect(await screen.findByRole('alert')).toHaveTextContent('Сбой загрузки')
  expect(screen.getByRole('status')).toHaveTextContent('"outfit":""')
})

test('author can add a catalog image when randomUUID is unavailable', async () => {
  const original = crypto.randomUUID
  Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: undefined })
  try {
    ;(uploadFile as jest.Mock).mockResolvedValue({ url: 'https://example.test/catalog.jpg' })
    const onChange = jest.fn()
    render(<RepeatImageOptionsEditor field={{ key: 'car', label: 'Машина', type: 'text' }}
      onChange={onChange} onBusyChange={() => {}} />)
    fireEvent.change(screen.getByLabelText('Добавить изображение варианта'), {
      target: { files: [new File(['car'], 'car.jpg', { type: 'image/jpeg' })] },
    })
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      image_choices: [expect.objectContaining({ id: expect.stringMatching(/^[a-zA-Z0-9_-]{1,48}$/),
        label: 'car', image_url: 'https://example.test/catalog.jpg' })],
    })))
  } finally {
    Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: original })
  }
})

test('simultaneous uploads in different groups preserve both selections', async () => {
  const pending: Array<(value: { url: string }) => void> = []
  ;(uploadFile as jest.Mock).mockImplementation(() => new Promise(resolve => pending.push(resolve)))
  function TwoGroups() {
    const [values, setValues] = useState<Record<string, string>>({})
    return <><RepeatPersonalizationFields fields={[...fields, { ...fields[0], key: 'car', label: 'Машина' }]}
      values={values} onChange={setValues} /><output>{JSON.stringify(values)}</output></>
  }
  render(<TwoGroups />)
  for (const label of ['Наряд девушки', 'Машина']) fireEvent.change(screen.getByLabelText(`Свой вариант: ${label}`), {
    target: { files: [new File(['photo'], 'own.jpg', { type: 'image/jpeg' })] },
  })
  await act(async () => {
    pending[0]({ url: 'https://example.test/outfit.jpg' })
    pending[1]({ url: 'https://example.test/car.jpg' })
  })
  expect(JSON.parse(screen.getByRole('status').textContent || '{}')).toEqual({
    outfit: 'upload:https://example.test/outfit.jpg', car: 'upload:https://example.test/car.jpg',
  })
})
