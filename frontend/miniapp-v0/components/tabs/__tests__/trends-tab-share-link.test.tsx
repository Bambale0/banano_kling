import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { TrendsTab } from '@/components/tabs/trends-tab'
import { useApp } from '@/lib/app-context'
import { fetchPrompts, fetchPromptLink } from '@/lib/api'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({
  fetchPrompts: jest.fn(), fetchPromptLink: jest.fn(), deactivatePrompt: jest.fn(),
  submitPrompt: jest.fn(), uploadFile: jest.fn(), sendMiniAppClientLog: jest.fn(),
}))
jest.mock('@/lib/trend-admin-api', () => ({ updateTrendPreview: jest.fn() }))
jest.mock('@/lib/genjutsu-api', () => ({ genjutsuCall: jest.fn(), openGenjutsu: jest.fn() }))
jest.mock('@/components/trend-runner-dialog', () => ({ TrendRunnerDialog: () => null }))

const link = 'https://t.me/fixture_bot/app?startapp=prompt_1606_ref_EXACT%2Bcode&mode=compact'
const trend = {
  id: 1606, title: 'Фото для видео тренда', description: '', prompt_text: '',
  category: 'photo', tags: ['trend'], uses_count: 0, likes: 0,
  repeat_cost: 2, preview_url: null, model: 'banana_pro', author_id: 1,
  status: 'approved', generation_settings: { kind: 'image', user_input: 'photo', model: 'banana_pro', ratio: '1:1' },
}
const writeText = jest.fn()
const execCopy = jest.fn()
const openTelegramLink = jest.fn()

beforeEach(() => {
  jest.clearAllMocks()
  ;(useApp as jest.Mock).mockReturnValue({
    state: { mode: 'live', user: { isAdmin: false }, imageModels: [
      { id: 'banana_pro', label: 'Nano Banana Pro', description: '', cost: 2, ratios: ['1:1'], max_references: 8 },
    ], videoModels: [] },
    trendToRun: null, setTrendToRun: jest.fn(),
  })
  ;(fetchPrompts as jest.Mock).mockResolvedValue([trend])
  ;(fetchPromptLink as jest.Mock).mockResolvedValue(link)
  Object.defineProperty(window.Telegram!.WebApp!, 'platform', { configurable: true, value: 'ios' })
  window.Telegram!.WebApp!.openTelegramLink = openTelegramLink
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  Object.defineProperty(navigator, 'share', { configurable: true, value: undefined })
  Object.defineProperty(document, 'execCommand', { configurable: true, value: execCopy })
  writeText.mockRejectedValue(new DOMException('Clipboard denied', 'NotAllowedError'))
  execCopy.mockReturnValue(false)
})

async function openShare() {
  render(<TrendsTab />)
  fireEvent.click(await screen.findByRole('button', { name: 'Ссылка' }))
  return await screen.findByRole('dialog', { name: 'Ссылка на тренд' })
}

it('on iOS fetches the exact referral link without attempting a doomed async auto-copy', async () => {
  const dialog = await openShare()
  const input = within(dialog).getByRole('textbox', { name: 'Ссылка на тренд' }) as HTMLInputElement
  expect(input).toHaveValue(link)
  expect(within(dialog).getByText(/Ссылка готова/)).toBeInTheDocument()
  expect(writeText).not.toHaveBeenCalled()
  expect(execCopy).not.toHaveBeenCalled()
  expect(screen.queryByText('Не удалось скопировать ссылку')).not.toBeInTheDocument()
  expect(fetchPromptLink).toHaveBeenCalledTimes(1)
  expect(fetchPromptLink).toHaveBeenCalledWith(1606)
  fireEvent.focus(input)
  expect(input.selectionStart).toBe(0)
  expect(input.selectionEnd).toBe(link.length)
})

it('survives total iOS clipboard denial with manual selection and a native phone menu', async () => {
  const nativeShare = jest.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'share', { configurable: true, value: nativeShare })
  const dialog = await openShare()
  const retry = within(dialog).getByRole('button', { name: 'Скопировать ссылку' })
  fireEvent.click(retry)
  expect(execCopy).toHaveBeenCalledTimes(2)
  await within(dialog).findByText(/Telegram не разрешил запись в буфер/)
  expect(within(dialog).getByRole('textbox', { name: 'Ссылка на тренд' })).toHaveValue(link)
  fireEvent.click(within(dialog).getByRole('button', { name: 'Через меню телефона' }))
  expect(nativeShare).toHaveBeenCalledWith({ url: link })
  expect(within(dialog).queryByText('Ссылка скопирована')).not.toBeInTheDocument()
  expect(fetchPromptLink).toHaveBeenCalledTimes(1)
})

it('copies on a fresh tap while preserving the exact server-owned referral URL', async () => {
  execCopy.mockReturnValue(true)
  const dialog = await openShare()
  fireEvent.click(within(dialog).getByRole('button', { name: 'Скопировать ссылку' }))
  expect(execCopy).toHaveBeenCalledTimes(1)
  await waitFor(() => expect(within(dialog).getByRole('status')).toHaveTextContent('Ссылка скопирована'))
  expect(fetchPromptLink).toHaveBeenCalledTimes(1)
})

it('retains one-tap Android copy when Clipboard API is available', async () => {
  Object.defineProperty(window.Telegram!.WebApp!, 'platform', { configurable: true, value: 'android' })
  writeText.mockResolvedValue(undefined)
  const dialog = await openShare()
  await waitFor(() => expect(within(dialog).getByRole('status')).toHaveTextContent('Ссылка скопирована'))
  expect(within(dialog).getByRole('textbox', { name: 'Ссылка на тренд' })).toHaveValue(link)
  expect(writeText).toHaveBeenCalledTimes(1)
  expect(writeText).toHaveBeenCalledWith(link)
  expect(fetchPromptLink).toHaveBeenCalledTimes(1)
})

it('offers Telegram forwarding and manual copy even without navigator.share', async () => {
  const dialog = await openShare()
  fireEvent.click(within(dialog).getByRole('button', { name: 'Скопировать ссылку' }))
  await within(dialog).findByText(/Telegram не разрешил запись в буфер/)
  expect(within(dialog).queryByRole('button', { name: 'Через меню телефона' })).not.toBeInTheDocument()
  const forward = within(dialog).getByRole('link', { name: 'Поделиться в Telegram' })
  const href = forward.getAttribute('href') || ''
  expect(href).toBe('https://t.me/share/url?url=' + encodeURIComponent(link))
  expect(new URL(href).searchParams.get('url')).toBe(link)
  expect(fireEvent.click(forward)).toBe(false)
  expect(openTelegramLink).toHaveBeenCalledWith(href)
  expect(within(dialog).getByRole('textbox', { name: 'Ссылка на тренд' })).toHaveValue(link)
})

it('shows an API error in the share dialog and recovers after a retry', async () => {
  ;(fetchPromptLink as jest.Mock).mockRejectedValueOnce(new Error('Временная ошибка API'))
  const dialog = await openShare()
  await within(dialog).findByRole('alert')
  expect(within(dialog).getByRole('alert')).toHaveTextContent('Временная ошибка API')
  expect(within(dialog).queryByRole('textbox', { name: 'Ссылка на тренд' })).not.toBeInTheDocument()
  fireEvent.click(within(dialog).getByRole('button', { name: 'Повторить загрузку' }))
  await within(dialog).findByRole('textbox', { name: 'Ссылка на тренд' })
  expect(within(dialog).queryByRole('alert')).not.toBeInTheDocument()
  expect(fetchPromptLink).toHaveBeenCalledTimes(2)
})

it('never permits a javascript URL returned by an unexpected server response', async () => {
  ;(fetchPromptLink as jest.Mock).mockResolvedValueOnce('javascript:alert(1)')
  const dialog = await openShare()
  await within(dialog).findByRole('alert')
  expect(within(dialog).queryByRole('link', { name: 'Открыть ссылку' })).not.toBeInTheDocument()
  expect(within(dialog).queryByRole('link', { name: 'Поделиться в Telegram' })).not.toBeInTheDocument()
  expect(within(dialog).queryByRole('textbox', { name: 'Ссылка на тренд' })).not.toBeInTheDocument()
})

it('discards a late response after dismissing the share dialog', async () => {
  let resolveStale!: (url: string) => void
  ;(fetchPromptLink as jest.Mock).mockImplementationOnce(() => new Promise<string>((resolve) => { resolveStale = resolve }))
  render(<TrendsTab />)
  fireEvent.click(await screen.findByRole('button', { name: 'Ссылка' }))
  const dialog = await screen.findByRole('dialog', { name: 'Ссылка на тренд' })
  expect(within(dialog).getByText(/Получаем ссылку/)).toBeInTheDocument()
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Ссылка на тренд' })).not.toBeInTheDocument())
  resolveStale('https://t.me/old_broken_personal_link')
  fireEvent.click(screen.getByRole('button', { name: 'Ссылка' }))
  const fresh = await screen.findByRole('dialog', { name: 'Ссылка на тренд' })
  await within(fresh).findByRole('textbox', { name: 'Ссылка на тренд' })
  expect(within(fresh).getByRole('textbox', { name: 'Ссылка на тренд' })).toHaveValue(link)
  expect(fetchPromptLink).toHaveBeenCalledTimes(2)
})
