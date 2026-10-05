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
