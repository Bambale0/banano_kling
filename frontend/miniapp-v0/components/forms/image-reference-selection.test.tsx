import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ImageGeneratorForm } from './image-generator-form'
import { referenceLibraryAction, uploadFile } from '@/lib/api'
import type { ImageModel, UploadedFile } from '@/lib/types'

jest.mock('@/lib/api', () => ({
  referenceLibraryAction: jest.fn(), uploadFile: jest.fn(), sendMiniAppClientLog: jest.fn(),
}))
jest.mock('./model-select', () => ({ ModelSelect: () => null }))
jest.mock('./ratio-select', () => ({ RatioSelect: () => null }))
jest.mock('./quality-select', () => ({ QualitySelect: () => null }))

const folder = { id: 'a'.repeat(32), name: 'Мои фото', count: 0 }
const photo: UploadedFile = {
  id: 'file_face', name: 'face.jpg', url: 'https://example.test/face.jpg',
  type: 'image', size: 4, saved_reference_id: '10',
}
const model: ImageModel = {
  id: 'banana_pro', label: 'Nano Banana Pro', description: '', cost: 1,
  ratios: ['9:16'], requires_reference: false, max_references: 8,
}

beforeEach(() => { jest.clearAllMocks() })

test.each([false, true])('a photo uploaded inside the reference picker reaches generation (editing categories=%s)', async managing => {
  let saved = false
  jest.mocked(referenceLibraryAction).mockImplementation(async action => action === 'categories'
    ? { ok: true, categories: [folder], recent: [] }
    : { ok: true, items: saved ? [{ id: '10', title: 'face.jpg', filename: 'face.jpg', kind: 'image', url: photo.url, available: true }] : [], next_offset: null })
  jest.mocked(uploadFile).mockImplementation(async () => { saved = true; return photo })
  const submit = jest.fn().mockResolvedValue(false)
  render(<ImageGeneratorForm models={[model]} onSubmit={submit} isSubmitting={false} credits={10} />)
  expect(screen.getByText('Только по описанию')).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Preserve the person in my photo' } })
  fireEvent.click(screen.getByRole('button', { name: 'Мои референсы' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Мои фото (0)' }))
  if (managing) fireEvent.click(screen.getByRole('button', { name: 'Управлять категориями' }))
  fireEvent.change(await screen.findByLabelText('Загрузить и выбрать'), {
    target: { files: [new File(['face'], 'face.jpg', { type: 'image/jpeg' })] },
  })
  await waitFor(() => expect(uploadFile).toHaveBeenCalledWith('image_reference', expect.any(File), folder.id))
  await act(async () => { await jest.mocked(uploadFile).mock.results[0].value })
  fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' })
  expect(screen.getByText('По описанию и фото')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Запустить фото' }))
  await waitFor(() => expect(submit).toHaveBeenCalledWith(expect.objectContaining({ references: [photo.url] })))
})
