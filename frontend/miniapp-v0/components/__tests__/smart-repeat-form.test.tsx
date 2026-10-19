import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SmartRepeatForm } from '@/components/smart-repeat-form'
import { useApp } from '@/lib/app-context'
import { smartRepeatCall, type RepeatDraft } from '@/lib/smart-repeat-api'
import { uploadFile } from '@/lib/api'
import type { UploadedFile } from '@/lib/types'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/smart-repeat-api', () => ({ smartRepeatCall: jest.fn() }))
jest.mock('@/lib/api', () => ({ uploadFile: jest.fn() }))
jest.mock('@/lib/seedance25-api', () => ({ uploadSeedance25Video: jest.fn() }))
jest.mock('@/lib/wan3-prime-api', () => ({ uploadWan3PrimeReference: jest.fn() }))
const call = smartRepeatCall as jest.Mock
const upload = uploadFile as jest.Mock
let draft: RepeatDraft
const context = { state: { imageModels: [], videoModels: [], user: { credits: 100 }, savedReferences: [], recentTasks: [] },
  addTask: jest.fn(), setCredits: jest.fn(), addSavedReference: jest.fn(), refreshTasks: jest.fn(), selectTask: jest.fn() }
beforeEach(() => {
  jest.clearAllMocks()
  ;(useApp as jest.Mock).mockReturnValue(context)
  draft = { draft_id: 'draft', revision: 0, status: 'draft', slots: {}, preset_id: null, user_values: {}, quote: null,
    template: { contract_version: 1, source_id: 42, version: 1, model: 'banana_pro', type: 'image', presets: [], variables: [],
      slots: [{ slot_id: 'face', kind: 'image', role: 'reference', label: 'Ваше лицо', hint: '', binding: 'upload', required: true },
              { slot_id: 'car', kind: 'image', role: 'reference', label: 'Ваша машина', hint: '', binding: 'upload', required: true }] } }
  call.mockImplementation(async (action, payload) => {
    if (action === 'update') {
      draft = { ...draft, revision: draft.revision + 1, quote: null, slots: { ...draft.slots } }
      if (payload.operation === 'changes') draft.prompt_changes = payload.prompt_changes.trim()
      else if (payload.operation === 'values') draft.user_values = payload.user_values
      else if (payload.operation === 'remove') delete draft.slots[payload.slot_id]
      else draft.slots[payload.slot_id] = { state: payload.operation === 'begin' ? 'UPLOADING' : payload.operation === 'ready' ? 'READY' : 'PROCESSING',
        upload_token: payload.slot_id + '-lease', url: payload.url, asset_id: payload.slot_id + '-asset' }
    }
    if (action === 'quote') draft = { ...draft, quote: { cost: 10, quote_id: 'quote-1' } }
    if (action === 'launch') {
      draft = { ...draft, status: 'launched', task_id: 'task-1' }
      return { ok: true, task_id: 'task-1', status: 'queued', credits: 90 }
    }
    return draft
  })
})
test('reverse uploads remain named; unfinished files block quote; double click launches once', async () => {
  let finishUpload: (value: unknown) => void = () => {}
  upload.mockImplementationOnce(() => new Promise(resolve => { finishUpload = resolve }))
    .mockResolvedValue({ id: 'face', type: 'image', url: '/uploads/face.png', name: 'face.png' })
  render(<SmartRepeatForm sourceId={42} onClose={jest.fn()} />)
  const car = await screen.findByLabelText('Загрузить: Ваша машина')
  const calculate = screen.getByRole('button', { name: 'Рассчитать стоимость' })
  expect(calculate).toBeDisabled()
  fireEvent.change(car, { target: { files: [new File(['car'], 'car.png', { type: 'image/png' })] } })
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(1))
  expect(calculate).toBeDisabled()
  finishUpload({ id: 'car', type: 'image', url: '/uploads/car.png', name: 'car.png' })
  await waitFor(() => expect(screen.getByText('Загружено обязательных референсов: 1 / 2')).toBeInTheDocument())
  fireEvent.change(screen.getByLabelText('Загрузить: Ваше лицо'), { target: { files: [new File(['face'], 'face.png')] } })
  await waitFor(() => expect(calculate).toBeEnabled())
  const ready = call.mock.calls.filter(([action, payload]) => action === 'update' && payload.operation === 'ready')
  expect(ready.map(([, payload]) => [payload.slot_id, payload.url])).toEqual([['car', '/uploads/car.png'], ['face', '/uploads/face.png']])
  fireEvent.click(calculate)
  const launch = await screen.findByRole('button', { name: /Создать.*10/ })
  fireEvent.click(launch); fireEvent.click(launch)
  await waitFor(() => expect(context.addTask).toHaveBeenCalledTimes(1))
  expect(call.mock.calls.filter(([action]) => action === 'launch')).toHaveLength(1)
  expect(context.addTask.mock.calls[0][0].task_id).toBe('task-1')
})
test('ready files restore; removing one prevents launch', async () => {
  draft.slots = { face: { state: 'READY', asset_id: 'face', url: '/uploads/face.png' }, car: { state: 'READY', asset_id: 'car', url: '/uploads/car.png' } }
  render(<SmartRepeatForm sourceId={42} onClose={jest.fn()} />)
  const calculate = await screen.findByRole('button', { name: 'Рассчитать стоимость' })
  expect(calculate).toBeEnabled()
  fireEvent.click(screen.getAllByRole('button', { name: 'Удалить файл' })[0])
  await waitFor(() => expect(calculate).toBeDisabled())
  expect(call.mock.calls.filter(([action]) => action === 'launch')).toHaveLength(0)
})

test('saved library choices bind their ID to a named slot and restore the selected filename', async () => {
  const files: UploadedFile[] = [
    { id: 'saved_11', saved_reference_id: '11', name: 'portrait.jpg', type: 'image', url: '/uploads/one.jpg', size: 10 },
    { id: 'saved_12', saved_reference_id: '12', name: 'portrait.jpg', type: 'image', url: '/uploads/two.jpg', size: 10 },
  ]
  ;(useApp as jest.Mock).mockReturnValue({ ...context, state: { ...context.state, savedReferences: files } })
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action, payload) => {
    const result = await original(action, payload)
    if (action === 'update' && payload.operation === 'ready') {
      draft = { ...draft, slots: { ...draft.slots, [payload.slot_id]: { ...draft.slots[payload.slot_id],
        url: '/uploads/two.jpg', filename: 'portrait.jpg', saved_reference_id: '12' } } } as RepeatDraft
      return draft
    }
    return result
  })
  const rendered = render(<SmartRepeatForm sourceId={42} onClose={jest.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Выбрать файл: Ваше лицо' }))
  fireEvent.click(screen.getByRole('button', { name: 'Взять из сохранённых' }))
  const choices = await screen.findAllByRole('button', { name: 'Выбрать: portrait.jpg' })
  expect(screen.getByText('Загружено обязательных референсов: 0 / 2')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  fireEvent.click(choices[1])
  await waitFor(() => expect(screen.getByText('Выбрано: portrait.jpg')).toBeInTheDocument())
  const ready = call.mock.calls.find(([action, payload]) => action === 'update' && payload.operation === 'ready')?.[1]
  expect(ready).toMatchObject({ slot_id: 'face', saved_reference_id: '12' })
  expect(ready).not.toHaveProperty('url')
  expect(upload).not.toHaveBeenCalled()
  expect(screen.getByText('Загружено обязательных референсов: 1 / 2')).toBeInTheDocument()
  rendered.unmount()
  render(<SmartRepeatForm sourceId={42} onClose={jest.fn()} />)
  expect(await screen.findByText('Выбрано: portrait.jpg')).toBeInTheDocument()
  expect(screen.getByAltText('Ваше лицо')).toHaveAttribute('src', '/uploads/two.jpg')
})

test('changes editor stays inside the repeat and saves before close or quote', async () => {
  draft.slots = { face: { state: 'READY', asset_id: 'face', url: '/uploads/face.png' }, car: { state: 'READY', asset_id: 'car', url: '/uploads/car.png' } }
  const close = jest.fn()
  const rendered = render(<SmartRepeatForm sourceId={42} onClose={close} />)
  const editor = await screen.findByRole('textbox', { name: 'Что изменить' })
  fireEvent.change(editor, { target: { value: 'Синяя машина' } })
  fireEvent.click(screen.getByRole('button', { name: 'Закрыть повтор' }))
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1))
  expect(call.mock.calls.some(([action, body]) => action === 'update' && body.operation === 'changes' && body.prompt_changes === 'Синяя машина')).toBe(true)
  expect(call.mock.calls.some(([action]) => action === 'quote' || action === 'launch')).toBe(false)
  rendered.unmount()
  render(<SmartRepeatForm sourceId={42} onClose={close} />)
  expect(await screen.findByRole('textbox', { name: 'Что изменить' })).toHaveValue('Синяя машина')
  fireEvent.change(screen.getByRole('textbox', { name: 'Что изменить' }), { target: { value: 'Красная машина' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await screen.findByRole('button', { name: /Создать.*10/ })
  expect(draft.prompt_changes).toBe('Красная машина')
  expect(call.mock.calls.filter(([action]) => action === 'launch')).toHaveLength(0)
})

test('changing publication while edits save cannot quote or launch the old repeat', async () => {
  draft.slots = { face: { state: 'READY', asset_id: 'face', url: '/uploads/face.png' }, car: { state: 'READY', asset_id: 'car', url: '/uploads/car.png' } }
  draft.template.variables = [{ id: 'city', label: 'Город', required: true, max_length: 80 }]
  let finish: (value: unknown) => void = () => {}
  const original = call.getMockImplementation()!
  call.mockImplementation((action, payload) => {
    if (action === 'open' && payload.source_id === 43) return Promise.resolve({ ...draft, draft_id: 'other', template: { ...draft.template, source_id: 43, model: 'banana_2', variables: [] } })
    return action === 'update' && payload.operation === 'changes'
      ? new Promise(resolve => { finish = resolve }) : original(action, payload)
  })
  const rendered = render(<SmartRepeatForm sourceId={42} onClose={jest.fn()} />)
  fireEvent.change(await screen.findByRole('textbox', { name: 'Что изменить' }), { target: { value: 'New changes' } })
  fireEvent.change(screen.getByLabelText('Город'), { target: { value: 'Казань' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(call.mock.calls.some(([action, body]) => action === 'update' && body.operation === 'changes')).toBe(true))
  rendered.rerender(<SmartRepeatForm sourceId={43} onClose={jest.fn()} />)
  await screen.findByText('Модель исходной работы: banana_2')
  await act(async () => { finish(draft) })
  expect(screen.getByText('Модель исходной работы: banana_2')).toBeInTheDocument()
  expect(call.mock.calls.some(([action, body]) => action === 'update' && body.operation === 'values')).toBe(false)
  expect(call.mock.calls.some(([action]) => action === 'quote' || action === 'launch')).toBe(false)
})

test('late new-repeat response cannot replace another publication', async () => {
  draft.status = 'rejected'
  let finish: (value: unknown) => void = () => {}
  const previous = draft
  call.mockImplementation((action, body) => {
    if (action === 'open' && body.new) return new Promise(resolve => { finish = resolve })
    if (action === 'open' && body.source_id === 43) return Promise.resolve({ ...previous, draft_id: 'other', status: 'draft', prompt_changes: 'B changes', template: { ...previous.template, source_id: 43, model: 'banana_2' } })
    return Promise.resolve(previous)
  })
  const rendered = render(<SmartRepeatForm sourceId={42} onClose={jest.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить ещё раз' }))
  await waitFor(() => expect(call.mock.calls.some(([action, body]) => action === 'open' && body.new)).toBe(true))
  rendered.rerender(<SmartRepeatForm sourceId={43} onClose={jest.fn()} />)
  await screen.findByText('Модель исходной работы: banana_2')
  await act(async () => { finish({ ...previous, status: 'draft', prompt_changes: 'A changes' }) })
  expect(screen.getByText('Модель исходной работы: banana_2')).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'Что изменить' })).toHaveValue('B changes')
})
