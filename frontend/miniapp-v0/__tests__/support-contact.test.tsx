import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SupportPanel } from '@/components/workspace-sheet'
import { useApp } from '@/lib/app-context'
import { copyTextToClipboard } from '@/lib/clipboard'
import { toast } from 'sonner'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/clipboard', () => ({ copyTextToClipboard: jest.fn() }))

const mockedUseApp = jest.mocked(useApp)
const mockedCopy = jest.mocked(copyTextToClipboard)
const originalTelegram = window.Telegram

beforeEach(() => {
  mockedUseApp.mockReturnValue({
    state: { user: { supportContact: '@only_tany' } },
  } as ReturnType<typeof useApp>)
  jest.clearAllMocks()
  mockedCopy.mockResolvedValue(undefined)
  jest.spyOn(toast, 'success').mockImplementation(() => '')
  jest.spyOn(toast, 'error').mockImplementation(() => '')
})

afterEach(() => {
  window.Telegram = originalTelegram
  jest.restoreAllMocks()
})

test('support shows the configured administrator and a real Telegram link', () => {
  render(<SupportPanel />)
  expect(screen.getByText('@only_tany')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Написать администратору' })).toHaveAttribute(
    'href', 'https://t.me/only_tany',
  )
})

test('uses native Telegram navigation inside the Telegram Mini App', () => {
  const openTelegramLink = jest.fn()
  window.Telegram = { WebApp: { openTelegramLink } }
  render(<SupportPanel />)
  fireEvent.click(screen.getByRole('link', { name: 'Написать администратору' }))
  expect(openTelegramLink).toHaveBeenCalledWith('https://t.me/only_tany')
})

test('does not generate an unsafe or broken link if contact is missing', () => {
  mockedUseApp.mockReturnValue({
    state: { user: { supportContact: 'https://evil.example/path' } },
  } as ReturnType<typeof useApp>)
  render(<SupportPanel />)
  expect(screen.queryByRole('link', { name: 'Написать администратору' })).not.toBeInTheDocument()
})

test('copies the actual support message before announcing success', async () => {
  render(<SupportPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Скопировать текст' }))
  await waitFor(() => {
    expect(mockedCopy).toHaveBeenCalledWith(
      'Здравствуйте. Нужна помощь по задаче. Укажу номер задачи, выбранную модель и коротко опишу, что ожидал получить.',
    )
    expect(toast.success).toHaveBeenCalledWith('Текст скопирован')
  })
})

test('reports a clipboard failure instead of a false success toast', async () => {
  mockedCopy.mockRejectedValueOnce(new Error('clipboard unavailable'))
  render(<SupportPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Скопировать текст' }))
  await waitFor(() => {
    expect(toast.error).toHaveBeenCalledWith('Не удалось скопировать текст')
    expect(toast.success).not.toHaveBeenCalled()
  })
})
