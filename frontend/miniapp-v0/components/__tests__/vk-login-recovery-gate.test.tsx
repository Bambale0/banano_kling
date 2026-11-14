import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { VkLoginRecoveryGate } from '../vk-login-recovery-gate'

jest.mock('@/lib/api', () => ({
  getApiBasePath: () => '/mini-app/api',
}))

test('a verified VK platform with a locked shared shell never asks for Telegram login', () => {
  render(<VkLoginRecoveryGate />)
  const vkLink = screen.getByRole('link', { name: 'Войти через ВКонтакте' })
  expect(vkLink).toHaveAttribute('href', '/mini-app/api/account-preview/vk-login')
  expect(vkLink).toHaveAttribute('target', '_top')
  expect(screen.getByText(/Telegram для входа не требуется/)).toBeInTheDocument()
  expect(screen.queryByText(/Продолжите через Telegram/)).not.toBeInTheDocument()
})
