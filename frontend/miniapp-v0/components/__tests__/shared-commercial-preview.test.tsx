import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SharedCommercialPreview } from '../shared-commercial-preview'
import { fetchCommercialCatalog, fetchCommercialTerms, fetchOwnCommercialTerms, saveCommercialCatalog, saveCommercialTerms, createCommercialQuote } from '@/lib/shared-account-api'

jest.mock('@/lib/shared-account-api', () => ({
  fetchCommercialCatalog: jest.fn(), fetchCommercialTerms: jest.fn(), fetchOwnCommercialTerms: jest.fn(), findCommercialAccount: jest.fn(),
  saveCommercialCatalog: jest.fn(), saveCommercialTerms: jest.fn(), createCommercialQuote: jest.fn(),
}))
const catalog = { revision: 3, default_tariff_id: 'ordinary', default_partner_group_id: 'base',
  tariffs: { ordinary: { label: 'Обычный', prices: { 'photo:test': { amount: '2.5000', unit: 'job' as const } } } },
  partner_groups: { base: { label: 'Базовая', first_level_percent: '30.0000', second_level_percent: '7.0000', repeat_reward_rub: '5.00' } },
}
const target = { account_id: 'own-account', settings: { revision: 2, tariff_id: null, partner_group_id: null,
  first_level_percent: null, second_level_percent: null, repeat_reward_rub: null },
  effective: { tariff_id: 'ordinary', partner_group_id: 'base', first_level_percent: '30.0000', second_level_percent: '7.0000', repeat_reward_rub: '5.00' },
}
beforeEach(() => {
  jest.resetAllMocks()
  jest.mocked(fetchCommercialCatalog).mockResolvedValue(catalog)
  jest.mocked(fetchOwnCommercialTerms).mockResolvedValue(target)
  jest.mocked(fetchCommercialTerms).mockResolvedValue(target)
})

test('price editor sends exact strings and the loaded catalog revision', async () => {
  jest.mocked(saveCommercialCatalog).mockResolvedValue({ ...catalog, revision: 4 })
  render(<SharedCommercialPreview />)
  await screen.findByLabelText('Код тарифа')
  fireEvent.change(screen.getByLabelText('Код тарифа'), { target: { value: 'creator' } })
  fireEvent.change(screen.getByLabelText('Название тарифа'), { target: { value: 'Креатор' } })
  fireEvent.change(screen.getByLabelText('Позиция прайса'), { target: { value: 'photo:test' } })
  fireEvent.change(screen.getByLabelText('Стоимость в бананах'), { target: { value: '1,2500' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить цену' }))
  await screen.findByText('Цена сохранена в общем каталоге.')
  expect(saveCommercialCatalog).toHaveBeenCalledWith(expect.objectContaining({ revision: 3, tariffs: expect.objectContaining({
    creator: { label: 'Креатор', prices: { 'photo:test': { amount: '1.2500', unit: 'job' } } },
  }) }), expect.any(AbortSignal))
})

test('individual agreement preserves explicit zero separately from an inherited rate', async () => {
  jest.mocked(saveCommercialTerms).mockResolvedValue({ ...target, effective: { ...target.effective, first_level_percent: '40.0000', second_level_percent: '0.0000' } })
  render(<SharedCommercialPreview />)
  fireEvent.change(await screen.findByLabelText('Индивидуальный процент первого уровня'), { target: { value: '40' } })
  fireEvent.change(screen.getByLabelText('Индивидуальный процент второго уровня'), { target: { value: '0' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить условия аккаунта' }))
  await screen.findByText('Индивидуальные условия сохранены.')
  expect(saveCommercialTerms).toHaveBeenCalledWith(expect.objectContaining({ settings: expect.objectContaining({
    revision: 2, first_level_percent: '40', second_level_percent: '0', repeat_reward_rub: null,
  }) }), expect.any(AbortSignal))
  expect(screen.getByText('Действующая ставка: 40.0000%. Повтор: 5.00 ₽.')).toBeInTheDocument()
})

test('VK quote shows the server price and Lava without client-side role selection', async () => {
  jest.mocked(createCommercialQuote).mockResolvedValue({ id: 'quote', scope: 'preview', platform: 'vk', total: '2.5000', terms: target.effective, allowed_payment_providers: ['lava'] })
  render(<SharedCommercialPreview />)
  fireEvent.change(await screen.findByLabelText('Позиция для расчёта'), { target: { value: 'photo:test' } })
  fireEvent.click(screen.getByRole('button', { name: 'Рассчитать стоимость' }))
  expect(await screen.findByText('Стоимость: 2.5000 банана. Ставка: 30.0000%. Для ВК предусмотрена только Lava.')).toBeInTheDocument()
  await waitFor(() => expect(createCommercialQuote).toHaveBeenCalledWith('photo:test', 1, expect.any(AbortSignal)))
})

test.each([
  { override: null, groupRate: '40', effectiveRate: '40.0000' },
  { override: '40.0000', groupRate: '35', effectiveRate: '40.0000' },
])('refreshes inherited conditions after group edits while keeping individual terms: $override', async ({ override, groupRate, effectiveRate }) => {
  jest.mocked(fetchOwnCommercialTerms).mockResolvedValue({ ...target, settings: { ...target.settings, first_level_percent: override } })
  jest.mocked(saveCommercialCatalog).mockResolvedValue({ ...catalog, revision: 4, partner_groups: { base: { ...catalog.partner_groups.base, first_level_percent: groupRate + '.0000', repeat_reward_rub: '7.00' } } })
  jest.mocked(fetchCommercialTerms).mockResolvedValue({ ...target, effective: { ...target.effective, first_level_percent: effectiveRate, repeat_reward_rub: '7.00' } })
  render(<SharedCommercialPreview />)
  fireEvent.click(await screen.findByRole('button', { name: 'Базовая: 30.0000% / 7.0000%; повтор 5.00 ₽' }))
  fireEvent.change(screen.getByLabelText('Процент первого уровня'), { target: { value: groupRate } })
  fireEvent.change(screen.getByLabelText('Вознаграждение за повтор, ₽'), { target: { value: '7' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить группу' }))
  await screen.findByText('Партнёрская группа сохранена.')
  expect(screen.getByText(`Действующая ставка: ${effectiveRate}%. Повтор: 7.00 ₽.`)).toBeInTheDocument()
  expect(screen.getByLabelText('Индивидуальный процент первого уровня')).toHaveValue(override || '')
  expect(fetchCommercialTerms).toHaveBeenCalledWith('own-account', expect.any(AbortSignal))
})
