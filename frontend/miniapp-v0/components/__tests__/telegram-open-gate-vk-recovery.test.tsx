import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { TelegramOpenGate } from '../telegram-open-gate'

jest.mock('@/lib/app-context', () => ({
  useApp: () => ({ state: { isLoading: false } }),
}))

jest.mock('@/lib/api', () => ({
  getApiBasePath: () => '/mini-app/api',
  getRuntimeBotUsername: () => 'Neuromixx_bot',
  getStartParamFallback: () => '',
}))

test('a locked launch does not require Telegram to enter the VK Mini App', () => {
  render(<TelegramOpenGate />)
  const link = screen.getByRole('link', { name: 'Войти через ВКонтакте' })
  expect(link).toHaveAttribute('href', '/mini-app/api/account-preview/vk-login')
  expect(link).toHaveAttribute('target', '_top')
  expect(screen.getByText(/Telegram для входа не нужен/)).toBeInTheDocument()
})

test('the Telegram sign-in widget remains available alongside VK recovery', () => {
  render(<TelegramOpenGate />)
  expect(document.querySelector('script[data-telegram-login]'))
    .toHaveAttribute('data-telegram-login', 'Neuromixx_bot')
  expect(screen.getByRole('link', { name: 'Войти через ВКонтакте' })).toBeInTheDocument()
})
