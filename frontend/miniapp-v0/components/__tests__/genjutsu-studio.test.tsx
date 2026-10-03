import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { GenjutsuStudio } from '../genjutsu-studio'
import { genjutsuCall } from '@/lib/genjutsu-api'
import catalog from '../../../../bot/genjutsu/catalog.json'

jest.mock('@/lib/api', () => ({ getApiBasePath: () => '/mini-app/api', getInitData: () => 'signed-test', getStartParamFallback: () => '' }))
jest.mock('@/lib/genjutsu-api', () => ({ ...jest.requireActual('@/lib/genjutsu-api'), genjutsuCall: jest.fn() }))
jest.mock('../genjutsu-admin', () => ({ GenjutsuAdmin: () => null }))

const call = genjutsuCall as jest.Mock
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
