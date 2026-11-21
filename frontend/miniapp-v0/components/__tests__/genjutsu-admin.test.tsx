import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { GenjutsuAdmin } from '../genjutsu-admin'
import { genjutsuCall } from '@/lib/genjutsu-api'

jest.mock('@/lib/genjutsu-api', () => ({
  ...jest.requireActual('@/lib/genjutsu-api'),
  genjutsuCall: jest.fn(),
}))

const call = genjutsuCall as jest.MockedFunction<typeof genjutsuCall>
const templates = {
  failed: 'Работа не завершена', canceled: 'Работа отменена', partial: 'Частичный результат',
  moderation: 'Модерация', provider_failure: 'Ошибка провайдера', technical_failure: 'Техническая ошибка',
  canceled_steps: 'Шаги остановлены', no_charge: 'Списания не было',
  refund: 'Возвращено {refunded_credits}', charge: 'Списано {charged_credits}', details: 'Открыть подробности',
}
const settings = {
  public_enabled: false, admin_enabled: true, verified_operations: [],
  prices: { motion_transfer: { '720p': 1 }, object_swap: { '720p': 1 }, restyle: { '720p': 1 } },
  notification_templates: templates,
}

beforeEach(() => {
  jest.clearAllMocks()
  call.mockImplementation(async action => {
    if (action === 'settings') return { settings, version: 7, coverage: [] }
    if (action === 'admin_runs') return { items: [] }
    return { ok: true }
  })
})

test('admin edits notification copy through versioned settings without changing financial policy', async () => {
  const changed = jest.fn().mockResolvedValue(undefined)
  render(<GenjutsuAdmin onChanged={changed} />)
  const refund = await screen.findByLabelText('Возврат на баланс')
  expect(refund).toHaveAttribute('maxlength', '300')
  expect(screen.getByLabelText('Заголовок ошибки')).toHaveValue(templates.failed)
  expect(screen.getAllByRole('textbox', { hidden: true })).toHaveLength(11)
  const custom = 'На баланс возвращено {refunded_credits} бананов'
  fireEvent.change(refund, { target: { value: custom } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }))
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
  expect(call).toHaveBeenCalledWith('save_settings', {
    expected_version: 7,
    settings: { ...settings, notification_templates: { ...templates, refund: custom } },
  })
})

test('rejected template validation leaves the edit available and does not report saved settings', async () => {
  const changed = jest.fn().mockResolvedValue(undefined)
  call.mockImplementation(async action => {
    if (action === 'settings') return { settings, version: 7, coverage: [] }
    if (action === 'admin_runs') return { items: [] }
    throw new Error('Недопустимый шаблон уведомления')
  })
  render(<GenjutsuAdmin onChanged={changed} />)
  const refund = await screen.findByLabelText('Возврат на баланс')
  fireEvent.change(refund, { target: { value: '{prompt}' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Недопустимый шаблон уведомления')
  expect(refund).toHaveValue('{prompt}')
  expect(changed).not.toHaveBeenCalled()
  expect(screen.queryByText('Настройки сохранены')).not.toBeInTheDocument()
})

test('Light prices are edited independently by quality and public launch requires coverage', async () => {
  const changed = jest.fn().mockResolvedValue(undefined)
  const light = {
    ...settings,
    prices: {
      ...settings.prices,
      motion_transfer_light: { '480p': null, '720p': null, '1080p': null },
      object_swap_light: { '480p': null, '720p': null, '1080p': null },
    },
  }
  call.mockImplementation(async action => {
    if (action === 'settings') return { settings: light, version: 8, coverage: [] }
    if (action === 'admin_runs') return { items: [] }
    return { ok: true }
  })
  render(<GenjutsuAdmin onChanged={changed} />)

  expect(await screen.findByRole('region', { name: 'Тарифы Higgsfield Light' })).toBeInTheDocument()
  const lightRate = screen.getByLabelText('Перенос движения · Light · 720p · цена за секунду')
  expect(lightRate).toHaveValue(null)
  const openToPublic = screen.getByLabelText('Перенос движения · Light · открыть пользователям')
  expect(openToPublic).toBeDisabled()

  fireEvent.change(lightRate, { target: { value: '5' } })
  expect(screen.getByText('Ролик 5 с: 50 🍌')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }))
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
  expect(call).toHaveBeenCalledWith('save_settings', {
    expected_version: 8,
    settings: {
      ...light,
      prices: {
        ...light.prices,
        motion_transfer_light: { '480p': null, '720p': 5, '1080p': null },
      },
    },
  })
})

test('Light public switch unlocks only after all resolutions have verified admin results and prices', async () => {
  const light = {
    ...settings,
    prices: {
      ...settings.prices,
      motion_transfer_light: { '480p': 3, '720p': 5, '1080p': 7 },
      object_swap_light: { '480p': null, '720p': null, '1080p': null },
    },
  }
  call.mockImplementation(async action => {
    if (action === 'settings') return { settings: light, version: 9, coverage: [
      { operation: 'motion_transfer_light', resolution: '480p', step_id: '1' },
      { operation: 'motion_transfer_light', resolution: '720p', step_id: '2' },
      { operation: 'motion_transfer_light', resolution: '1080p', step_id: '3' },
    ] }
    if (action === 'admin_runs') return { items: [] }
    return { ok: true }
  })
  render(<GenjutsuAdmin onChanged={jest.fn().mockResolvedValue(undefined)} />)
  const ready = await screen.findByLabelText('Перенос движения · Light · открыть пользователям')
  const notReady = screen.getByLabelText('Замена объектов · Light · открыть пользователям')
  expect(ready).toBeEnabled()
  expect(notReady).toBeDisabled()
  fireEvent.click(ready)
  expect(ready).toBeChecked()
})

test('previously-approved public Light stays editable before full live coverage', async () => {
  const approved = {
    ...settings,
    public_enabled: true,
    verified_operations: ['motion_transfer_light'],
    prices: {
      ...settings.prices,
      motion_transfer_light: { '480p': 2, '720p': 4, '1080p': 8 },
      object_swap_light: { '480p': 2, '720p': 4, '1080p': 8 },
    },
  }
  call.mockImplementation(async action => {
    if (action === 'settings') return { settings: approved, version: 12, coverage: [
      { operation: 'motion_transfer_light', resolution: '480p', step_id: 'existing' },
    ] }
    if (action === 'admin_runs') return { items: [] }
    return { ok: true }
  })
  const changed = jest.fn().mockResolvedValue(undefined)
  render(<GenjutsuAdmin onChanged={changed} />)
  const active = await screen.findByLabelText('Перенос движения · Light · открыть пользователям')
  const inactive = screen.getByLabelText('Замена объектов · Light · открыть пользователям')
  expect(active).toBeChecked()
  expect(active).toBeEnabled()
  expect(inactive).toBeDisabled()
  fireEvent.click(active)
  expect(active).not.toBeChecked()
  expect(active).toBeEnabled()
  fireEvent.click(active)
  expect(active).toBeChecked()
  const price = screen.getByLabelText('Перенос движения · Light · 720p · цена за секунду')
  fireEvent.change(price, { target: { value: '6' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить настройки' }))
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
  expect(call).toHaveBeenCalledWith('save_settings', expect.objectContaining({
    expected_version: 12,
    settings: expect.objectContaining({
      public_enabled: true,
      verified_operations: ['motion_transfer_light'],
      prices: expect.objectContaining({
        motion_transfer_light: { '480p': 2, '720p': 6, '1080p': 8 },
      }),
    }),
  }))
})