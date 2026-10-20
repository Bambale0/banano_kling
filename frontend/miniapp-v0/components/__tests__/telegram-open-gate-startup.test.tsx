import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { TelegramOpenGate } from '../telegram-open-gate'
import { useApp } from '@/lib/app-context'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({ getApiBasePath: () => '/mini-app/api', getRuntimeBotUsername: () => 'synthetic_bot',
  getStartParamFallback: () => 'synthetic_work', hasTelegramInitData: () => true }))
const refreshTasks = jest.fn()

test('expired credentials still expose fresh Telegram authentication', async () => {
  ;(useApp as jest.Mock).mockReturnValue({ state: { isLoading: false, error: 'Войдите заново', bootstrapFailureKind: 'auth' }, refreshTasks })
  render(<TelegramOpenGate />)
  await waitFor(() => expect(document.querySelector('script[data-telegram-login="synthetic_bot"]')).not.toBeNull())
  expect(screen.queryByRole('button', { name: 'Повторить подключение' })).not.toBeInTheDocument()
})

test('transport failure preserves launch credentials and retries without a login widget', async () => {
  ;(useApp as jest.Mock).mockReturnValue({ state: { isLoading: false, error: 'Сеть недоступна', bootstrapFailureKind: 'network' }, refreshTasks })
  render(<TelegramOpenGate />)
  fireEvent.click(screen.getByRole('button', { name: 'Повторить подключение' }))
  expect(refreshTasks).toHaveBeenCalledTimes(1)
  expect(document.querySelector('script[data-telegram-login]')).toBeNull()
})
