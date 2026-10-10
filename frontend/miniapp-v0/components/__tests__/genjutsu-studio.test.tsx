import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { GenjutsuStudio } from '../genjutsu-studio'
import { type Quote, genjutsuCall, uploadGenjutsu } from '@/lib/genjutsu-api'
import catalog from '../../../../bot/genjutsu/catalog.json'

jest.mock('@/lib/api', () => ({ getApiBasePath: () => '/mini-app/api', getInitData: () => 'signed-test', getStartParamFallback: () => '' }))
jest.mock('@/lib/genjutsu-api', () => ({ ...jest.requireActual('@/lib/genjutsu-api'), genjutsuCall: jest.fn(), uploadGenjutsu: jest.fn() }))
jest.mock('../genjutsu-admin', () => ({ GenjutsuAdmin: () => <div>GENJUTSU_ADMIN_PANEL</div> }))

const call = genjutsuCall as jest.Mock
const uploadCall = uploadGenjutsu as jest.Mock
const initial = {}
const bootstrap = {
  catalog, configured: true, enabled: true, is_admin: false, credits: 1000,
  provider_ready: true, media_ready: true, config_version: 1,
  limits: { max_steps: 3, max_variants: 4, poll_seconds: 5 },
  prices: {}, projects: [], runs: [],
  assets: [{ id: 'video', kind: 'video', duration_ms: 8100, url: 'https://files.example/v.mp4' },
           { id: 'face', kind: 'image', url: 'https://files.example/p.png' }],
}

beforeEach(() => {
  jest.clearAllMocks(); sessionStorage.clear()
  uploadCall.mockReset()
  Object.defineProperty(global.crypto, 'randomUUID', { configurable: true, value: () => '11111111-2222-4333-8444-555555555555' })
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return bootstrap
    if (action === 'presets') return { items: [] }
    if (action === 'save_project') return { project: { id: 'project', revision: 1, title: body.title, plan: body.plan } }
    if (action === 'quote') return { quote: { id: 'quote-one', expires_ms: Date.now() + 300000, total_credits: 90, allocations: [], plan_hash: 'hash' } }
    throw new Error(`Unexpected action: ${action}`)
  })
})

async function inputs() {
  await screen.findByLabelText('Видео из библиотеки')
  fireEvent.change(screen.getByLabelText('Видео из библиотеки'), { target: { value: 'video' } })
  fireEvent.change(screen.getByLabelText('Добавить референс к шагу 1'), { target: { value: 'face' } })
}

test('all API qualities are available and mode change never silently drops reference roles', async () => {
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.change(screen.getByLabelText('Качество шага 1'), { target: { value: '1080p' } })
  fireEvent.change(screen.getByLabelText('Роль референса 1 шага 1'), { target: { value: 'wardrobe' } })
  fireEvent.change(screen.getByLabelText('Операция шага 1'), { target: { value: 'restyle' } })
  expect(screen.getByLabelText('Роль референса 1 шага 1')).toHaveValue('wardrobe')
  expect(screen.getByLabelText('Качество шага 1')).toHaveValue('1080p')
  expect(await screen.findByText(/Референсы сохранены, но не подходят/)).toBeInTheDocument()
})

test('server quote is shown and a lost submit response reuses the same idempotency key', async () => {
  let starts = 0
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action !== 'start') return original(action, body)
    starts += 1
    if (starts === 1) throw new Error('Ответ потерян')
    return { run: { id: 'run-one', project_id: 'project', state: 'completed', steps: [], credits: 910, created_ms: Date.now() } }
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('90 бананов')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Запустить' }))
  expect(await screen.findByText('Ответ потерян')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Запустить' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Запустить' }))
  await screen.findByText('run-one')
  const requests = call.mock.calls.filter(([action]) => action === 'start')
  expect(requests).toHaveLength(2)
  expect(requests[0][1].request_key).toBe(requests[1][1].request_key)
  expect(requests[0][1]).not.toHaveProperty('admin_free')
})


test('private recipe mode collects declared fields, quotes server-side and never exposes its hidden plan', async () => {
  const recipe = {
    id: 'a'.repeat(32),
    title: 'Secret trend',
    slots: [],
    user_fields: [{ key: 'Имя', label: 'Имя', type: 'text', required: true, max_length: 160 }],
    steps: [{ operation: 'restyle', resolution: '720p' }],
    variants: 1,
    continuation: 'automatic',
    current_cost: 20,
  }
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'recipe_get') return { recipe }
    if (action === 'recipe_quote') {
      expect(body).toEqual({ recipe_id: recipe.id, reference_asset_ids: [], user_values: { 'Имя': 'Анна' } })
      return { recipe, quote: { id: 'recipe-quote', expires_ms: Date.now() + 300000, total_credits: 20, allocations: [], plan_hash: 'hidden' } }
    }
    if (action === 'start') {
      return { run: { id: 'recipe-run', state: 'completed', private_recipe: 1, admin_free: 0, cancel_requested: 0, steps: [], credits: 980, created_ms: Date.now() } }
    }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={{ recipe_id: recipe.id }} onClose={jest.fn()} />)
  expect(await screen.findByText('Secret trend')).toBeInTheDocument()
  expect(screen.queryByText(/hidden plan/i)).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Имя'), { target: { value: 'Анна' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('20 бананов')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Запустить тренд' }))
  expect(await screen.findByText('recipe-run')).toBeInTheDocument()
})


test('admin recipe publication requires and sends a completed verification run', async () => {
  const adminBootstrap = {
    ...bootstrap,
    is_admin: true,
    runs: [{ id: 'verified-run', project_id: 'project', state: 'completed', created_ms: Date.now() }],
  }
  const recipe = {
    id: 'b'.repeat(32), title: 'Verified recipe', slots: [{ step_index: 0, reference_index: 0, role: 'character', label: 'Фото 1' }],
    user_fields: [], steps: [{ operation: 'motion_transfer', resolution: '720p' }], variants: 1,
    continuation: 'automatic', current_cost: 10,
  }
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return adminBootstrap
    if (action === 'recipe_publish') {
      expect(body.verification_run_id).toBe('verified-run')
      expect(body.project_id).toBe('project')
      expect(body.revision).toBe(1)
      expect(body.source_binding).toBe('user')
      return { recipe }
    }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.click(screen.getByRole('button', { name: 'Создать приватный рецепт' }))
  expect(await screen.findByText(/Рецепт готов:/)).toBeInTheDocument()
  expect(call.mock.calls.some(([action]) => action === 'recipe_publish')).toBe(true)
})


test('admin entry opens Genjutsu management immediately for an admin', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return { ...bootstrap, is_admin: true }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={{ admin: true }} onClose={jest.fn()} />)
  expect(await screen.findByText('GENJUTSU_ADMIN_PANEL')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Управление' })).toBeInTheDocument()
})

test('admin entry never exposes management to a non-admin', async () => {
  render(<GenjutsuStudio initial={{ admin: true }} onClose={jest.fn()} />)
  expect(await screen.findByLabelText('Видео из библиотеки')).toBeInTheDocument()
  expect(screen.queryByText('GENJUTSU_ADMIN_PANEL')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Управление' })).not.toBeInTheDocument()
})


test('trend recipe accepts one video reference plus photo references before quoting', async () => {
  const recipe = {
    id: 'c'.repeat(32),
    title: 'Motion trend',
    source_slot: { kind: 'video', label: 'Видео-референс' },
    slots: [{ step_index: 0, reference_index: 0, role: 'character', label: 'Фото героя' }],
    user_fields: [],
    steps: [{ operation: 'motion_transfer', resolution: '720p' }],
    variants: 1,
    continuation: 'automatic',
    current_cost: 20,
  }
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'recipe_get') return { recipe }
    if (action === 'recipe_quote') {
      expect(body).toEqual({
        recipe_id: recipe.id,
        source_asset_id: 'recipe-video',
        reference_asset_ids: ['recipe-face'],
        user_values: {},
      })
      return { recipe, quote: { id: 'recipe-quote', expires_ms: Date.now() + 300000, total_credits: 24, allocations: [], plan_hash: 'hidden' } }
    }
    return original(action, body)
  })
  uploadCall.mockImplementation(async (file: File, kind: string) => ({
    id: kind === 'video' ? 'recipe-video' : 'recipe-face',
    kind,
    url: kind === 'video' ? 'https://files.example/video.mp4' : 'https://files.example/face.png',
    ...(kind === 'video' ? { duration_ms: 5000 } : {}),
  }))

  render(<GenjutsuStudio initial={{ recipe_id: recipe.id }} onClose={jest.fn()} />)
  expect(await screen.findByText('Motion trend')).toBeInTheDocument()

  fireEvent.change(screen.getByLabelText('Видео-референс'), {
    target: { files: [new File(['video'], 'motion.mp4', { type: 'video/mp4' })] },
  })
  await waitFor(() => expect(uploadCall).toHaveBeenCalledWith(expect.any(File), 'video'))
  await waitFor(() => expect(screen.getByText('Видео загружено — нажмите, чтобы заменить')).toBeInTheDocument())

  fireEvent.change(screen.getByLabelText('Фото героя'), {
    target: { files: [new File(['image'], 'face.png', { type: 'image/png' })] },
  })
  await waitFor(() => expect(uploadCall).toHaveBeenCalledWith(expect.any(File), 'image'))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('24 бананов')).toBeInTheDocument()
  expect(uploadCall).toHaveBeenCalledWith(expect.any(File), 'video')
  expect(uploadCall).toHaveBeenCalledWith(expect.any(File), 'image')
})

test('mobile operation chooser is a bounded grid without horizontal scrolling', async () => {
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await screen.findByLabelText('Видео из библиотеки')
  const chooser = screen.getByTestId('genjutsu-operation-grid')
  expect(chooser.className).toContain('grid')
  expect(chooser.className).not.toContain('overflow-x-auto')
})

// Public UI/API regression coverage for the actual source-video range.
function expectVideoRange(start: number, end: number) {
  const startInput = screen.getByLabelText('Начало, сек.')
  const endInput = screen.getByLabelText('Конец, сек.')
  expect(startInput).toBeVisible()
  expect(endInput).toBeVisible()
  expect(startInput).toHaveValue(start)
  expect(endInput).toHaveValue(end)
  expect(startInput.closest('details')).toBeNull()
  expect(endInput.closest('details')).toBeNull()
}

function quoteWithDuration(id = 'duration-quote', seconds = 9, credits = 117): Quote {
  return {
    id, expires_ms: Date.now() + 300000, total_credits: credits, plan_hash: `hash-${id}`,
    allocations: [{ variant: 0, ordinal: 0, operation: 'motion_transfer', billable_seconds: seconds,
      credits_per_second: 13, reserved_credits: credits, maximum_reserve: false }],
  }
}

function sourceRecipe() {
  return {
    id: 'd'.repeat(32), title: 'User video trend',
    source_slot: { kind: 'video', label: 'Видео-референс' }, slots: [], user_fields: [],
    steps: [{ operation: 'motion_transfer', resolution: '720p' }], variants: 1,
    continuation: 'automatic', current_cost: 20,
  }
}

test('an 8.1 second source defaults to its full visible range and quotes without preparing a fragment', async () => {
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  expectVideoRange(0, 8.1)
  expect(screen.queryByText('Выбрать фрагмент')).not.toBeInTheDocument()
  expect(screen.queryByDisplayValue('5')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('90 бананов')).toBeInTheDocument()
  expect(call).toHaveBeenCalledWith('save_project', expect.objectContaining({
    plan: expect.objectContaining({ source_asset_id: 'video' }),
  }))
  expect(call).toHaveBeenCalledWith('quote', { project_id: 'project', revision: 1 })
  expect(call.mock.calls.filter(([action]) => action === 'trim')).toHaveLength(0)
})

test('source duration stays exact while billable seconds and price come from the server allocation', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'quote') return { quote: quoteWithDuration() }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  expectVideoRange(0, 8.1)
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('117 бананов')).toBeInTheDocument()
  expect(screen.getByText(/9\s*(?:сек|с)(?:\.|\s|$)/)).toBeVisible()
  expect(screen.getByText(/117\s*🍌/)).toBeVisible()
  expectVideoRange(0, 8.1)
})

test('the server quote shows reference seconds plus requested generation seconds', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'quote') {
      const quote = quoteWithDuration('split-duration-quote', 20, 260)
      return { quote: { ...quote, allocations: [
        { ...quote.allocations[0], reference_seconds: 12, generation_seconds: 8 },
      ] } }
    }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('260 бананов')).toBeInTheDocument()
  expect(screen.getByText(/12 с видеорефа \+ 8 с генерации = 20 с к оплате/)).toBeVisible()
})


test('replacing the selected source resets a pending range to the replacement full duration and removes its old quote', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return { ...bootstrap, assets: [...bootstrap.assets,
      { id: 'replacement', kind: 'video', duration_ms: 12345, url: 'https://files.example/replacement.mp4' }] }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await screen.findByText('90 бананов')
  await waitFor(() => expect(screen.getByLabelText('Конец, сек.')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: '6.25' } })
  expect(screen.queryByRole('button', { name: 'Запустить' })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Видео из библиотеки'), { target: { value: 'replacement' } })
  expectVideoRange(0, 12.345)
  expect(screen.queryByText('90 бананов')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await screen.findByText('90 бананов')
  const saves = call.mock.calls.filter(([action]) => action === 'save_project')
  expect(saves[saves.length - 1][1].plan.source_asset_id).toBe('replacement')
  expect(call.mock.calls.filter(([action]) => action === 'trim')).toHaveLength(0)
})

test('upload and task import initialize the visible range from their returned source metadata', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'import') return { asset: { id: 'imported', kind: 'video', duration_ms: 9876, url: 'https://files.example/imported.mp4' } }
    return original(action, body)
  })
  uploadCall.mockResolvedValue({ id: 'uploaded', kind: 'video', duration_ms: 10123, url: 'https://files.example/uploaded.mp4' })
  render(<GenjutsuStudio initial={{ task_id: 'previous-video-task' }} onClose={jest.fn()} />)
  await waitFor(() => expect(screen.getByLabelText('Видео из библиотеки')).toHaveValue('imported'))
  expectVideoRange(0, 9.876)
  fireEvent.change(screen.getByLabelText(/Заменить видео/), { target: { files: [new File(['video'], 'replacement.mp4', { type: 'video/mp4' })] } })
  await waitFor(() => expect(screen.getByLabelText('Видео из библиотеки')).toHaveValue('uploaded'))
  expectVideoRange(0, 10.123)
  expect(call.mock.calls.filter(([action]) => action === 'trim')).toHaveLength(0)
})

test('a 31 second source is not silently cut to the provider maximum and must apply a valid range before quoting', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return { ...bootstrap, assets: bootstrap.assets.map(asset => asset.id === 'video' ? { ...asset, duration_ms: 31000 } : asset) }
    if (action === 'trim') return { asset: { id: 'shortened', kind: 'video', duration_ms: 29960, url: 'https://files.example/shortened.mp4' } }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  expectVideoRange(0, 31)
  expect(screen.getByRole('alert')).toHaveTextContent(/30/)
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(call.mock.calls.filter(([action]) => action === 'quote' || action === 'trim')).toHaveLength(0)
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: '30' } })
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Применить фрагмент' }))
  await waitFor(() => expect(screen.getByLabelText('Видео из библиотеки')).toHaveValue('shortened'))
  expect(call).toHaveBeenCalledWith('trim', { asset_id: 'video', start_ms: 0, end_ms: 30000 })
  expectVideoRange(0, 29.96)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled())
})

test.each([
  ['empty start', '', '8.1'],
  ['empty end', '0', ''],
  ['negative start', '-0.001', '8.1'],
  ['reversed bounds', '7', '4'],
  ['equal bounds', '4', '4'],
  ['end after source', '0', '8.101'],
  ['below operation minimum', '0', '3.999'],
])('invalid range (%s) never requests a trim or quote', async (_description, start, end) => {
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.change(screen.getByLabelText('Начало, сек.'), { target: { value: start } })
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: end } })
  const apply = screen.getByRole('button', { name: 'Применить фрагмент' })
  const calculate = screen.getByRole('button', { name: 'Рассчитать стоимость' })
  expect(apply).toBeDisabled()
  expect(calculate).toBeDisabled()
  fireEvent.click(apply)
  fireEvent.click(calculate)
  expect(call.mock.calls.filter(([action]) => action === 'trim' || action === 'quote')).toHaveLength(0)
})

test('manual range applies millisecond bounds and quotes the returned asset with its actual duration', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'trim') return { asset: { id: 'trimmed-video', kind: 'video', duration_ms: 6610, url: 'https://files.example/trimmed.mp4' } }
    if (action === 'quote') return { quote: quoteWithDuration('trimmed-quote', 7, 91) }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.change(screen.getByLabelText('Начало, сек.'), { target: { value: '1.123' } })
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: '7.777' } })
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  expect(call.mock.calls.filter(([action]) => action === 'trim')).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: 'Применить фрагмент' }))
  await waitFor(() => expect(screen.getByLabelText('Видео из библиотеки')).toHaveValue('trimmed-video'))
  expect(call).toHaveBeenCalledWith('trim', { asset_id: 'video', start_ms: 1123, end_ms: 7777 })
  expectVideoRange(0, 6.61)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('91 бананов')).toBeInTheDocument()
  expect(screen.getByText(/7\s*(?:сек|с)(?:\.|\s|$)/)).toBeVisible()
  expect(call).toHaveBeenCalledWith('save_project', expect.objectContaining({ plan: expect.objectContaining({ source_asset_id: 'trimmed-video' }) }))
  expect(call.mock.calls.filter(([action]) => action === 'trim')).toHaveLength(1)
})

test('range editing clears a quoted launch and its provider-cost acknowledgment', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return { ...bootstrap, is_admin: true }
    if (action === 'trim') return { asset: { id: 'admin-trimmed', kind: 'video', duration_ms: 6000, url: 'https://files.example/admin-trimmed.mp4' } }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  const acknowledgment = await screen.findByLabelText('Подтверждаю реальный расход в Higgsfield.')
  await waitFor(() => expect(screen.getByLabelText('Конец, сек.')).toBeEnabled())
  fireEvent.click(acknowledgment)
  expect(screen.getByRole('button', { name: 'Запустить' })).toBeEnabled()
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: '6' } })
  expect(screen.queryByRole('button', { name: 'Запустить' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Подтверждаю реальный расход в Higgsfield.')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Применить фрагмент' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByLabelText('Подтверждаю реальный расход в Higgsfield.')).not.toBeChecked()
  expect(screen.getByRole('button', { name: 'Запустить' })).toBeDisabled()
})

test.each(['operation', 'title'])('a late quote cannot resurrect a launch after a newer %s edit', async editKind => {
  let resolveQuote!: (value: { quote: Quote }) => void
  const pendingQuote = new Promise<{ quote: Quote }>(resolve => { resolveQuote = resolve })
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'quote') return pendingQuote
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  await waitFor(() => expect(call.mock.calls.filter(([action]) => action === 'quote')).toHaveLength(1))
  if (editKind === 'operation') fireEvent.click(screen.getByRole('button', { name: 'Другой герой или предмет' }))
  else fireEvent.change(screen.getByLabelText('Название работы'), { target: { value: 'Updated while quoting' } })
  await act(async () => { resolveQuote({ quote: quoteWithDuration('obsolete-quote') }); await pendingQuote })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled())
  expect(screen.queryByText('117 бананов')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Запустить' })).not.toBeInTheDocument()
  expect(call.mock.calls.filter(([action]) => action === 'start')).toHaveLength(0)
})

test('a user-source recipe shows the full uploaded range and only the current server quote price', async () => {
  const recipe = sourceRecipe()
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'recipe_get') return { recipe }
    if (action === 'recipe_quote') return { recipe, quote: quoteWithDuration('recipe-full', 9, 117) }
    return original(action, body)
  })
  uploadCall.mockResolvedValue({ id: 'recipe-full-video', kind: 'video', duration_ms: 8100, url: 'https://files.example/recipe-full.mp4' })
  render(<GenjutsuStudio initial={{ recipe_id: recipe.id }} onClose={jest.fn()} />)
  await screen.findByText(recipe.title)
  expect(screen.queryByText(/Текущая стоимость рецепта:/)).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Видео-референс'), { target: { files: [new File(['video'], 'source.mp4', { type: 'video/mp4' })] } })
  await waitFor(() => expect(screen.getByLabelText('Конец, сек.')).toHaveValue(8.1))
  expectVideoRange(0, 8.1)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('117 бананов')).toBeInTheDocument()
  expect(screen.getByText(/9\s*(?:сек|с)(?:\.|\s|$)/)).toBeVisible()
  expect(call).toHaveBeenCalledWith('recipe_quote', { recipe_id: recipe.id, source_asset_id: 'recipe-full-video', reference_asset_ids: [], user_values: {} })
  expect(call.mock.calls.filter(([action]) => action === 'trim' || action === 'quote')).toHaveLength(0)
  expect(screen.queryByText(/20\s*🍌/)).not.toBeInTheDocument()
})

test('a user-source recipe applies an optional range and resets it when its source is replaced', async () => {
  const recipe = sourceRecipe()
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'recipe_get') return { recipe }
    if (action === 'trim') return { asset: { id: 'recipe-trimmed', kind: 'video', duration_ms: 4960, url: 'https://files.example/recipe-trimmed.mp4' } }
    if (action === 'recipe_quote') return { recipe, quote: quoteWithDuration('recipe-trim-quote', 5, 65) }
    return original(action, body)
  })
  uploadCall.mockResolvedValueOnce({ id: 'recipe-original', kind: 'video', duration_ms: 8100, url: 'https://files.example/recipe-original.mp4' })
    .mockResolvedValueOnce({ id: 'recipe-replacement', kind: 'video', duration_ms: 12400, url: 'https://files.example/recipe-replacement.mp4' })
  render(<GenjutsuStudio initial={{ recipe_id: recipe.id }} onClose={jest.fn()} />)
  await screen.findByText(recipe.title)
  fireEvent.change(screen.getByLabelText('Видео-референс'), { target: { files: [new File(['video'], 'source.mp4', { type: 'video/mp4' })] } })
  await waitFor(() => expect(screen.getByLabelText('Конец, сек.')).toHaveValue(8.1))
  await waitFor(() => expect(screen.getByLabelText('Начало, сек.')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Начало, сек.'), { target: { value: '1' } })
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: '6' } })
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Применить фрагмент' }))
  await waitFor(() => expect(screen.getByLabelText('Конец, сек.')).toHaveValue(4.96))
  expectVideoRange(0, 4.96)
  expect(call).toHaveBeenCalledWith('trim', { asset_id: 'recipe-original', start_ms: 1000, end_ms: 6000 })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('65 бананов')).toBeInTheDocument()
  expect(call).toHaveBeenCalledWith('recipe_quote', { recipe_id: recipe.id, source_asset_id: 'recipe-trimmed', reference_asset_ids: [], user_values: {} })
  await waitFor(() => expect(screen.getByLabelText('Видео-референс')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Видео-референс'), { target: { files: [new File(['replacement'], 'replacement.mp4', { type: 'video/mp4' })] } })
  await waitFor(() => expect(screen.getByLabelText('Конец, сек.')).toHaveValue(12.4))
  expectVideoRange(0, 12.4)
  expect(screen.queryByText('65 бананов')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Запустить тренд' })).not.toBeInTheDocument()
})

// Additional interruption and authoritative-metadata edge cases.
test.each(['operation', 'title'])('a late trim cannot replace the source after a newer %s edit', async editKind => {
  const trimmedAsset = { id: 'obsolete-trim', kind: 'video', duration_ms: 5960, url: 'https://files.example/obsolete-trim.mp4' }
  let resolveTrim!: (value: { asset: typeof trimmedAsset }) => void
  const pendingTrim = new Promise<{ asset: typeof trimmedAsset }>(resolve => { resolveTrim = resolve })
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'trim') return pendingTrim
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: '6' } })
  fireEvent.click(screen.getByRole('button', { name: 'Применить фрагмент' }))
  await waitFor(() => expect(call).toHaveBeenCalledWith('trim', { asset_id: 'video', start_ms: 0, end_ms: 6000 }))
  if (editKind === 'operation') fireEvent.click(screen.getByRole('button', { name: 'Другой герой или предмет' }))
  else fireEvent.change(screen.getByLabelText('Название работы'), { target: { value: 'Updated while trimming' } })
  await act(async () => { resolveTrim({ asset: trimmedAsset }); await pendingTrim })
  await waitFor(() => expect(screen.getByLabelText('Видео из библиотеки')).toBeEnabled())
  expect(screen.getByLabelText('Видео из библиотеки')).toHaveValue('video')
  expect(screen.queryByRole('option', { name: /obsolete/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Запустить' })).not.toBeInTheDocument()
  expect(call.mock.calls.filter(([action]) => action === 'quote')).toHaveLength(0)
})

test('a trim result above the duration limit remains invalid without clamping its returned metadata', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return { ...bootstrap, assets: bootstrap.assets.map(asset => asset.id === 'video' ? { ...asset, duration_ms: 31000 } : asset) }
    if (action === 'trim') return { asset: { id: 'still-too-long', kind: 'video', duration_ms: 30021, url: 'https://files.example/still-too-long.mp4' } }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: '30' } })
  fireEvent.click(screen.getByRole('button', { name: 'Применить фрагмент' }))
  await waitFor(() => expect(screen.getByLabelText('Видео из библиотеки')).toHaveValue('still-too-long'))
  expect(call).toHaveBeenCalledWith('trim', { asset_id: 'video', start_ms: 0, end_ms: 30000 })
  expectVideoRange(0, 30.021)
  expect(screen.getAllByRole('alert').some(alert => /30/.test(alert.textContent || ''))).toBe(true)
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(call.mock.calls.filter(([action]) => action === 'quote')).toHaveLength(0)
})

test.each([
  ['missing', undefined],
  ['NaN', Number.NaN],
  ['infinite', Number.POSITIVE_INFINITY],
])('a source with %s duration never substitutes a default or permits a quote', async (_description, durationMs) => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return { ...bootstrap, assets: bootstrap.assets.map(asset => asset.id === 'video' ? { ...asset, duration_ms: durationMs } : asset) }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  expect(screen.getByRole('alert')).toBeVisible()
  expect(screen.queryByDisplayValue('5')).not.toBeInTheDocument()
  const calculate = screen.getByRole('button', { name: 'Рассчитать стоимость' })
  expect(calculate).toBeDisabled()
  fireEvent.click(calculate)
  expect(call.mock.calls.filter(([action]) => action === 'trim' || action === 'quote')).toHaveLength(0)
})

test('opening a saved project and restoring its older revision reset the range to each source actual duration', async () => {
  const projectPlan = (sourceAssetId: string) => ({
    source_asset_id: sourceAssetId,
    steps: [{ operation: 'motion_transfer', resolution: '720p', prompt: '', preserve: '', preset_id: null,
      references: [{ asset_id: 'face', role: 'character', label: '', binding: 'user' }] }],
    variants: 1, continuation: 'automatic',
  })
  const savedProject = { id: 'saved-project', revision: 2, title: 'Saved source', plan: projectPlan('saved-video') }
  const olderProject = { ...savedProject, revision: 1, title: 'Earlier source', plan: projectPlan('older-video') }
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return {
      ...bootstrap, projects: [savedProject], assets: [...bootstrap.assets,
        { id: 'saved-video', kind: 'video', duration_ms: 11234, url: 'https://files.example/saved.mp4' },
        { id: 'older-video', kind: 'video', duration_ms: 6111, url: 'https://files.example/older.mp4' }],
    }
    if (action === 'project') return { project: body.revision === 1 ? olderProject : savedProject }
    if (action === 'versions') return { items: [{ revision: 1, title: olderProject.title }, { revision: 2, title: savedProject.title }] }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: '6' } })
  fireEvent.change(screen.getByLabelText('Открыть проект'), { target: { value: 'saved-project' } })
  await waitFor(() => expect(screen.getByLabelText('Видео из библиотеки')).toHaveValue('saved-video'))
  expectVideoRange(0, 11.234)
  await waitFor(() => expect(screen.getByLabelText('Конец, сек.')).toBeEnabled())
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: '9' } })
  fireEvent.change(screen.getByLabelText('Восстановить версию'), { target: { value: '1' } })
  await waitFor(() => expect(screen.getByLabelText('Видео из библиотеки')).toHaveValue('older-video'))
  expectVideoRange(0, 6.111)
  expect(call).toHaveBeenCalledWith('project', { project_id: 'saved-project', revision: 1 })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled())
  expect(call.mock.calls.filter(([action]) => action === 'trim')).toHaveLength(0)
})


test('switching from A to B and back to A never restores an abandoned pending fragment', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return { ...bootstrap, assets: [...bootstrap.assets,
      { id: 'other-video', kind: 'video', duration_ms: 12400, url: 'https://files.example/other.mp4' }] }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: '6' } })
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Видео из библиотеки'), { target: { value: 'other-video' } })
  expectVideoRange(0, 12.4)
  fireEvent.change(screen.getByLabelText('Видео из библиотеки'), { target: { value: 'video' } })
  expectVideoRange(0, 8.1)
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled()
  expect(call.mock.calls.filter(([action]) => action === 'trim')).toHaveLength(0)
})

test.each([
  ['negative sub-millisecond start', '-0.0001', '8.1'],
  ['sub-millisecond end after source', '0', '8.1004'],
])('raw invalid bounds (%s) cannot become valid through millisecond rounding', async (_description, start, end) => {
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.change(screen.getByLabelText('Начало, сек.'), { target: { value: start } })
  fireEvent.change(screen.getByLabelText('Конец, сек.'), { target: { value: end } })
  expect(screen.getByRole('alert')).toBeVisible()
  const calculate = screen.getByRole('button', { name: 'Рассчитать стоимость' })
  expect(calculate).toBeDisabled()
  fireEvent.click(calculate)
  const apply = screen.queryByRole('button', { name: 'Применить фрагмент' })
  if (apply) {
    expect(apply).toBeDisabled()
    fireEvent.click(apply)
  }
  expect(call.mock.calls.filter(([action]) => action === 'trim' || action === 'quote')).toHaveLength(0)
})

test('a millisecond-precise full source remains valid despite binary floating-point conversion', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return { ...bootstrap, assets: bootstrap.assets.map(asset => asset.id === 'video' ? { ...asset, duration_ms: 4001 } : asset) }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  expectVideoRange(0, 4.001)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('90 бананов')).toBeInTheDocument()
  expect(call.mock.calls.filter(([action]) => action === 'trim')).toHaveLength(0)
})


test('saved sources outside the latest asset page restore canonical duration and remain quotable', async () => {
  const savedProject = { id: 'old-project', revision: 1, title: 'Old source', plan: {
    source_asset_id: 'old-source', steps: [{ operation: 'motion_transfer', resolution: '720p',
      prompt: '', preserve: '', preset_id: null, references: [] }], variants: 1, continuation: 'automatic',
  } }
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return { ...bootstrap, projects: [savedProject],
      assets: Array.from({ length: 100 }, (_, i) => ({ id: `new-${i}`, kind: 'video', duration_ms: 5000, url: null })) }
    if (action === 'project') return { project: savedProject, source_asset: { id: 'old-source', kind: 'video', duration_ms: 10056 } }
    if (action === 'versions') return { items: [] }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await screen.findByLabelText('Открыть проект')
  fireEvent.change(screen.getByLabelText('Открыть проект'), { target: { value: savedProject.id } })
  await waitFor(() => expect(screen.getByLabelText('Конец, сек.')).toHaveValue(10.056))
  expectVideoRange(0, 10.056)
  fireEvent.click(screen.getByRole('button', { name: 'Мои работы' }))
  await screen.findByText('Здесь появятся принятые задачи. Черновики доступны в разделе «Создать».')
  await act(async () => { await Promise.resolve() })
  fireEvent.click(screen.getByRole('button', { name: 'Создать' }))
  expectVideoRange(0, 10.056)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('90 бананов')).toBeInTheDocument()
  expect(call.mock.calls.filter(([action]) => action === 'trim')).toHaveLength(0)
})

test('admin quote distinguishes zero balance debit from the user tariff', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return { ...bootstrap, is_admin: true }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  await inputs()
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('0 бананов')).toBeInTheDocument()
  expect(screen.getByText(/Пользовательский тариф: 90 бананов/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Запустить' })).toBeDisabled()
})


test('repeating a run restores source metadata outside the latest asset page', async () => {
  const runPlan = { source_asset_id: 'history-source', steps: [{ operation: 'motion_transfer', resolution: '720p',
    prompt: '', preserve: '', preset_id: null, references: [] }], variants: 1, continuation: 'automatic' }
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'run') return { run: { id: 'old-run', project_id: 'old-project', plan: runPlan, state: 'completed',
      created_ms: Date.now(), credits: 1000, steps: [{ id: 'old-step', ordinal: 0, variant: 0, status: 'completed',
        spec: runPlan.steps[0], reserved_credits: 88, refunded_credits: 0, actual_credits: 88,
        source_asset: { id: 'history-source', kind: 'video', duration_ms: 10056, url: null } }] } }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={{ run_id: 'old-run' }} onClose={jest.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Повторить с настройками' }))
  await waitFor(() => expect(screen.getByLabelText('Конец, сек.')).toHaveValue(10.056))
  expectVideoRange(0, 10.056)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled())
})


test('an unavailable saved source clearly blocks calculation until replaced', async () => {
  const project = { id: 'missing-project', revision: 1, title: 'Missing source', plan: {
    source_asset_id: 'missing-source', steps: [{ operation: 'motion_transfer', resolution: '720p',
      prompt: '', preserve: '', preset_id: null, references: [] }], variants: 1, continuation: 'automatic',
  } }
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return { ...bootstrap, projects: [project] }
    if (action === 'project') return { project, source_asset: null }
    if (action === 'versions') return { items: [] }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={initial} onClose={jest.fn()} />)
  fireEvent.change(await screen.findByLabelText('Открыть проект'), { target: { value: project.id } })
  expect(await screen.findByText(/Исходное видео недоступно/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Видео из библиотеки'), { target: { value: 'video' } })
  expectVideoRange(0, 8.1)
  expect(screen.queryByText(/Исходное видео недоступно/)).not.toBeInTheDocument()
})

test.each(['Повторить с настройками', 'Редактировать результат'])('%s retains source when history refresh resolves during previous draft save', async button => {
  const runPlan = { source_asset_id: 'history-source', steps: [{ operation: 'motion_transfer', resolution: '720p',
    prompt: '', preserve: '', preset_id: null, references: [] }], variants: 1, continuation: 'automatic' }
  let refreshCount = 0
  let resolveRefresh!: (value: unknown) => void
  let resolveSave!: (value: unknown) => void
  let pendingPlan: unknown
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') {
      refreshCount += 1
      if (refreshCount === 1) return bootstrap
      return new Promise(resolve => { resolveRefresh = resolve })
    }
    if (action === 'save_project') {
      pendingPlan = body.plan
      return new Promise(resolve => { resolveSave = resolve })
    }
    if (action === 'run') return { run: { id: 'old-run', project_id: 'old-project', plan: runPlan, state: 'completed',
      created_ms: Date.now(), credits: 1000, steps: [{ id: 'old-step', ordinal: 0, variant: 0, status: 'completed',
        spec: runPlan.steps[0], reserved_credits: 88, refunded_credits: 0, actual_credits: 88,
        source_asset: { id: 'history-source', kind: 'video', duration_ms: 10056, url: null },
        output_asset: { id: 'history-output', kind: 'video', duration_ms: 10000, url: 'https://files.example/output.mp4' } }] } }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={{ run_id: 'old-run' }} onClose={jest.fn()} />)
  await screen.findByRole('button', { name: 'Повторить с настройками' })
  fireEvent.click(screen.getByRole('button', { name: 'Создать' }))
  await inputs()
  fireEvent.click(screen.getByRole('button', { name: 'Мои работы' }))
  fireEvent.click(screen.getByRole('button', { name: button }))
  await waitFor(() => expect(resolveSave).toBeDefined())
  await act(async () => { resolveRefresh(bootstrap) })
  await act(async () => { resolveSave({ project: { id: 'draft', revision: 1, title: 'Draft', plan: pendingPlan } }) })
  await waitFor(() => expect(screen.getByLabelText('Конец, сек.')).toHaveValue(button === 'Повторить с настройками' ? 10.056 : 10))
  expect(screen.getByRole('button', { name: 'Рассчитать стоимость' })).toBeEnabled()
})


test('provider moderation is explained without exposing the misleading provider_nsfw code', async () => {
  const run = {
    id: '8fed8d02bfdf4b2bbe0be1b9d1ce8572',
    project_id: 'project',
    state: 'failed',
    admin_free: 0,
    cancel_requested: 0,
    credits: 1000,
    created_ms: Date.now(),
    steps: [{
      id: 'step-one',
      variant: 0,
      ordinal: 0,
      status: 'failed',
      spec: { operation: 'motion_transfer', resolution: '480p' },
      reserved_credits: 128,
      actual_credits: 128,
      refunded_credits: 128,
      error_code: 'provider_nsfw',
      delivery_status: null,
      delivery_error: null,
    }],
  }
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'run') return { run }
    return original(action, body)
  })

  render(<GenjutsuStudio initial={{ run_id: run.id }} onClose={jest.fn()} />)

  expect(await screen.findByText('Модерация провайдера')).toBeInTheDocument()
  expect(screen.getByText(/возможны ложные срабатывания/i)).toBeInTheDocument()
  expect(screen.queryByText(/provider_nsfw/i)).not.toBeInTheDocument()
  expect(screen.getByText(/возврат 128 🍌/i)).toBeInTheDocument()
})
