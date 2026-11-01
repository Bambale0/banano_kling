import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { PersonalReferenceLibrary } from './personal-reference-library'
import { referenceLibraryAction, uploadFile } from '@/lib/api'

jest.mock('@/lib/api', () => ({ referenceLibraryAction: jest.fn(), uploadFile: jest.fn() }))
const folder = { id: 'a'.repeat(32), name: 'Одежда', count: 2 }
const dress = { id: '10', kind: 'image', title: 'Чёрное платье', filename: 'dress.png', url: 'https://example.test/dress.png', available: true }

beforeEach(() => { jest.clearAllMocks() })

test('user selects an outfit from a personal category without uploading again', async () => {
  ;(referenceLibraryAction as jest.Mock).mockImplementation(async action => action === 'categories'
    ? { categories: [folder], recent: [] } : { items: [dress], next_offset: null })
  const select = jest.fn()
  render(<PersonalReferenceLibrary kind="image" onSelect={select} />)
  fireEvent.click(screen.getByRole('button', { name: 'Мои референсы' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Одежда (2)' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Выбрать Чёрное платье' }))
  expect(select).toHaveBeenCalledWith(expect.objectContaining({ url: dress.url, saved_reference_id: dress.id }))
  expect(uploadFile).not.toHaveBeenCalled()
})

test('new category upload passes the category into the existing upload protocol', async () => {
  let saved = false
  ;(uploadFile as jest.Mock).mockImplementation(async () => { saved = true; return { url: dress.url } })
  ;(referenceLibraryAction as jest.Mock).mockImplementation(async action => action === 'categories'
    ? { categories: [folder], recent: [] } : { items: saved ? [dress] : [], next_offset: null })
  render(<PersonalReferenceLibrary kind="image" />)
  fireEvent.click(screen.getByRole('button', { name: 'Мои референсы' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Одежда (2)' }))
  fireEvent.change(await screen.findByLabelText('Добавить файл в категорию'), {
    target: { files: [new File(['dress'], 'dress.png', { type: 'image/png' })] },
  })
  await waitFor(() => expect(uploadFile).toHaveBeenCalledWith('image_reference', expect.any(File), folder.id))
  expect(await screen.findByRole('img', { name: dress.title })).toBeInTheDocument()
})

test('show more keeps the first page and appends the next page', async () => {
  const first = Array.from({ length: 40 }, (_, index) => ({ ...dress, id: String(index), title: `Образ ${index}` }))
  ;(referenceLibraryAction as jest.Mock).mockImplementation(async (action, body) => action === 'categories'
    ? { categories: [folder], recent: [] }
    : body.offset ? { items: [{ ...dress, id: 'last', title: 'Последний наряд' }], next_offset: null }
      : { items: first, next_offset: 40 })
  render(<PersonalReferenceLibrary kind="image" onSelect={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Мои референсы' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Одежда (2)' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Показать ещё' }))
  expect(await screen.findByRole('button', { name: 'Выбрать Последний наряд' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Выбрать Образ 0' })).toBeInTheDocument()
})
