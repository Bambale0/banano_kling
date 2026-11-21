import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { GenjutsuStudio } from '../genjutsu-studio'
import { genjutsuCall, uploadGenjutsu } from '@/lib/genjutsu-api'
import catalog from '../../../../bot/genjutsu/catalog.json'

jest.mock('@/lib/api', () => ({ getApiBasePath: () => '/mini-app/api', getInitData: () => 'signed-test', getStartParamFallback: () => '' }))
jest.mock('@/lib/genjutsu-api', () => ({ ...jest.requireActual('@/lib/genjutsu-api'), genjutsuCall: jest.fn(), uploadGenjutsu: jest.fn() }))
jest.mock('../genjutsu-admin', () => ({ GenjutsuAdmin: () => <div>GENJUTSU_ADMIN_PANEL</div> }))

const call = genjutsuCall as jest.Mock
const uploadCall = uploadGenjutsu as jest.Mock
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

test('editing a Light result preserves its original prompt, mode, resolution, references and quote payload', async () => {
  const original = call.getMockImplementation()!
  const step = {
    operation: 'motion_transfer_light', resolution: '480p',
    prompt: 'Replace the original face with the face in Image 1',
    preserve: 'motion, timing and camera', preset_id: null,
    references: [{ asset_id: 'face', role: 'character', label: 'new performer', binding: 'user' }],
  }
  const originalPlan = {
    source_asset_id: 'video', steps: [step], variants: 2, continuation: 'automatic',
  }
  const edited = {
    id: 'output-video', kind: 'video', duration_ms: 10000, url: 'https://files.example/output.mp4',
  }
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'bootstrap') return {
      ...bootstrap,
      limits: { ...bootstrap.limits, verified_operations: ['motion_transfer_light', 'object_swap_light'] },
    }
    if (action === 'run') return { run: {
      id: 'old-run', project_id: 'old-project', state: 'completed', private_recipe: 0, admin_free: 0,
      plan: originalPlan, created_ms: Date.now(), credits: 1000,
      steps: [{ id: 'old-step', ordinal: 0, variant: 0, status: 'completed', spec: step,
        reserved_credits: 80, refunded_credits: 0, actual_credits: 80,
        source_asset: bootstrap.assets[0], output_asset: edited }],
    } }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={{ run_id: 'old-run' }} onClose={jest.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Редактировать результат' }))
  expect(await screen.findByRole('combobox', { name: 'Модель Genjutsu' })).toHaveValue('light')
  expect(screen.getByLabelText('Операция шага 1')).toHaveValue('motion_transfer_light')
  expect(screen.getByLabelText('Качество шага 1')).toHaveValue('480p')
  expect(screen.getByLabelText('Видео из библиотеки')).toHaveValue('output-video')
  expect(screen.getByLabelText('Что изменить?')).toHaveValue(step.prompt)
  expect(screen.getByLabelText('Что сохранить')).toHaveValue(step.preserve)
  expect(screen.getByLabelText('Роль референса 1 шага 1')).toHaveValue('character')
  expect(screen.getByLabelText('Назначение референса 1 шага 1')).toHaveValue('new performer')
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('90 бананов')).toBeInTheDocument()
  const saved = call.mock.calls.filter(([action]) => action === 'save_project')
  expect(saved).toHaveLength(1)
  const plan = saved[0][1].plan
  expect(plan.source_asset_id).toBe('output-video')
  expect(plan.steps).toEqual([step])
  expect(plan.variants).toBe(2)
  expect(plan.continuation).toBe('automatic')
  expect(call.mock.calls.some(([action]) => action === 'start')).toBe(false)
})

test('editing a protected recipe result never restores hidden instructions or references', async () => {
  const original = call.getMockImplementation()!
  call.mockImplementation(async (action: string, body: Record<string, unknown>) => {
    if (action === 'run') return { run: {
      id: 'private-run', state: 'completed', private_recipe: 1, admin_free: 0,
      created_ms: Date.now(), credits: 1000,
      steps: [{ id: 'private-step', ordinal: 0, variant: 0, status: 'completed',
        spec: { operation: 'object_swap_light', resolution: '480p' },
        reserved_credits: 80, refunded_credits: 0, actual_credits: 80,
        output_asset: { id: 'private-output', kind: 'video', duration_ms: 8000,
          url: 'https://files.example/private-output.mp4' } }],
    } }
    return original(action, body)
  })
  render(<GenjutsuStudio initial={{ run_id: 'private-run' }} onClose={jest.fn()} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Редактировать результат' }))
  expect(await screen.findByLabelText('Видео из библиотеки')).toHaveValue('private-output')
  expect(screen.getByLabelText('Что изменить?')).toHaveValue('')
  expect(screen.getByRole('combobox', { name: 'Модель Genjutsu' })).toHaveValue('light')
  expect(screen.getByLabelText('Качество шага 1')).toHaveValue('480p')
  expect(screen.queryByLabelText('Роль референса 1 шага 1')).not.toBeInTheDocument()
})