import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AccountReferencePreview } from '../account-reference-preview'
import { fetchAccountReferencePhotos, removeAccountReferencePhoto, saveAccountReferencePhoto } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchAccountReferencePhotos: jest.fn(), removeAccountReferencePhoto: jest.fn(), saveAccountReferencePhoto: jest.fn(),
}))

const photo = { id: 'a'.repeat(32), mime: 'image/png' as const, width: 3, height: 2, size_bytes: 78,
  created_at_epoch: 123, thumbnail: new Blob(['photo'], { type: 'image/png' }) }

beforeEach(() => {
  jest.resetAllMocks()
  URL.createObjectURL = jest.fn(() => 'blob:owned-photo')
  URL.revokeObjectURL = jest.fn()
  jest.mocked(fetchAccountReferencePhotos).mockResolvedValue({ references: [], next_offset: null })
})

test('closed photo control makes no request and loads only after explicit opening', async () => {
  render(<AccountReferencePreview />)
  expect(fetchAccountReferencePhotos).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Фото аккаунта' }))
  expect(await screen.findByText('Пока нет сохранённых фото.')).toBeInTheDocument()
  expect(fetchAccountReferencePhotos).toHaveBeenCalledWith(0, expect.any(AbortSignal))
})

test('owned private thumbnails use object URLs and release them on collapse', async () => {
  jest.mocked(fetchAccountReferencePhotos).mockResolvedValue({ references: [photo], next_offset: null })
  render(<AccountReferencePreview />)
  fireEvent.click(screen.getByRole('button', { name: 'Фото аккаунта' }))
  expect(await screen.findByAltText('Фото 1')).toHaveAttribute('src', 'blob:owned-photo')
  fireEvent.click(screen.getByRole('button', { name: 'Фото аккаунта' }))
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:owned-photo')
})

test('saved upload stays acknowledged when its preview is unavailable', async () => {
  jest.mocked(saveAccountReferencePhoto).mockResolvedValue(photo)
  jest.mocked(fetchAccountReferencePhotos).mockResolvedValueOnce({ references: [], next_offset: null })
    .mockResolvedValueOnce({ references: [{ ...photo, thumbnail: null }], next_offset: null })
  render(<AccountReferencePreview />)
  fireEvent.click(screen.getByRole('button', { name: 'Фото аккаунта' }))
  await screen.findByText('Пока нет сохранённых фото.')
  const file = new File(['photo'], 'photo.png', { type: 'image/png' })
  fireEvent.change(screen.getByLabelText('Добавить фото'), { target: { files: [file] } })
  expect(await screen.findByText('Фото сохранено.')).toBeInTheDocument()
  expect(await screen.findByText('Превью временно недоступно.')).toBeInTheDocument()
  expect(saveAccountReferencePhoto).toHaveBeenCalledWith(file, expect.any(AbortSignal))
})

test('removing from the library refreshes metadata and releases the old thumbnail', async () => {
  jest.mocked(fetchAccountReferencePhotos).mockResolvedValueOnce({ references: [photo], next_offset: null })
    .mockResolvedValueOnce({ references: [], next_offset: null })
  jest.mocked(removeAccountReferencePhoto).mockResolvedValue()
  render(<AccountReferencePreview />)
  fireEvent.click(screen.getByRole('button', { name: 'Фото аккаунта' }))
  await screen.findByAltText('Фото 1')
  fireEvent.click(screen.getByRole('button', { name: 'Убрать из библиотеки' }))
  expect(await screen.findByText('Фото убрано из библиотеки.')).toBeInTheDocument()
  expect(removeAccountReferencePhoto).toHaveBeenCalledWith(photo.id, expect.any(AbortSignal))
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:owned-photo')
})

test('late response after unmount cannot create or retain private object URLs', async () => {
  let resolve!: (value: { references: typeof photo[]; next_offset: null }) => void
  jest.mocked(fetchAccountReferencePhotos).mockReturnValue(new Promise(done => { resolve = done }))
  const view = render(<AccountReferencePreview />)
  fireEvent.click(screen.getByRole('button', { name: 'Фото аккаунта' }))
  await waitFor(() => expect(fetchAccountReferencePhotos).toHaveBeenCalled())
  const signal = jest.mocked(fetchAccountReferencePhotos).mock.calls[0][1]!
  view.unmount()
  expect(signal.aborted).toBe(true)
  await act(async () => { resolve({ references: [photo], next_offset: null }) })
  expect(URL.createObjectURL).not.toHaveBeenCalled()
})

test('failed authentication never fabricates an empty private library', async () => {
  jest.mocked(fetchAccountReferencePhotos).mockRejectedValue(new Error('Откройте приложение заново для подтверждения входа.'))
  render(<AccountReferencePreview />)
  fireEvent.click(screen.getByRole('button', { name: 'Фото аккаунта' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Откройте приложение заново')
  expect(screen.queryByText('Пока нет сохранённых фото.')).not.toBeInTheDocument()
})
