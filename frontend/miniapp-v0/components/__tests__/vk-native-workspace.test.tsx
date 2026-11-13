import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { VkNativeWorkspace } from '../vk-native-workspace'

jest.mock('../vk-standalone-discovery', () => ({
  VkStandaloneDiscovery: ({ surface }: { surface?: string }) =>
    <section aria-label="VK-native content" data-testid="native-content">{surface}</section>,
}))

jest.mock('../vk-native-services', () => ({
  VkNativeServices: ({ onTabChange }: { onTabChange: (tab: number) => void }) =>
    <section role="status" aria-label="Сервисы NEUROMIX">
      <h3>Сервисы NEUROMIX</h3>
      <button type="button" onClick={() => onTabChange(7)}>Нативные партнёры</button>
    </section>,
}))

afterEach(() => {
  window.history.replaceState({}, '', '/')
})

test('unlinked native VK shell has the exact seven shared navigation tabs, not Motion', () => {
  render(<VkNativeWorkspace />)
  const nav = screen.getByRole('navigation', { name: 'Разделы приложения' })
  expect(nav.querySelectorAll('button')).toHaveLength(7)
  for (const label of ['Студия', 'Фото', 'Видео', 'Лента', 'Тренды', 'Сервисы', 'Профиль']) {
    expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
  }
  expect(screen.queryByRole('button', { name: 'Motion' })).not.toBeInTheDocument()
  expect(screen.getByTestId('native-content')).toHaveTextContent('studio')
})

test.each([
  ['Фото', 'photo'],
  ['Видео', 'video'],
  ['Лента', 'feed'],
  ['Тренды', 'trends'],
  ['Профиль', 'profile'],
])('VK shared %s tab routes only to native %s content without Telegram store', (label, surface) => {
  render(<VkNativeWorkspace />)
  fireEvent.click(screen.getByRole('button', { name: label }))
  expect(screen.getByTestId('native-content')).toHaveTextContent(surface)
  expect(screen.getByRole('button', { name: label })).toHaveAttribute('aria-current', 'page')
})

test('unsupported services never instantiate legacy Telegram service clients', () => {
  render(<VkNativeWorkspace />)
  fireEvent.click(screen.getByRole('button', { name: 'Сервисы' }))
  expect(screen.queryByTestId('native-content')).not.toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Сервисы NEUROMIX')
  expect(screen.queryByText('Привяжите Telegram')).not.toBeInTheDocument()
})

test('VK feed deep link opens the same Feed navigation tab, never a trend', () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001#remix_370766_ref_ABC')
  render(<VkNativeWorkspace />)
  expect(screen.getByRole('button', { name: 'Лента' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByTestId('native-content')).toHaveTextContent('feed')
})

test('VK trend deep link opens native Trends tab', () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001#prompt_31')
  render(<VkNativeWorkspace />)
  expect(screen.getByRole('button', { name: 'Тренды' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByTestId('native-content')).toHaveTextContent('trends')
})

test('back navigation returns to exact public VK tab and never manufactures Telegram login', () => {
  render(<VkNativeWorkspace />)
  fireEvent.click(screen.getByRole('button', { name: 'Фото' }))
  window.history.replaceState({}, '', '/#feed_30')
  fireEvent(window, new Event('popstate'))
  expect(screen.getByRole('button', { name: 'Лента' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByTestId('native-content')).toHaveTextContent('feed')
})

test('native tab switch clears stale public deep link while preserving signed VK launch query', () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001&sign=signed#prompt_31')
  render(<VkNativeWorkspace />)
  fireEvent.click(screen.getByRole('button', { name: 'Фото' }))
  expect(window.location.hash).toBe('')
  expect(window.location.search).toContain('sign=signed')
  expect(screen.getByTestId('native-content')).toHaveTextContent('photo')
})

test('VK account linking invite is not discarded by navigating the native tabs', () => {
  const invite = 'a'.repeat(43)
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001#link_' + invite)
  render(<VkNativeWorkspace />)
  fireEvent.click(screen.getByRole('button', { name: 'Профиль' }))
  expect(window.location.hash).toBe('#link_' + invite)
})

test('native VK services partner shortcut navigates to signed VK profile, not Telegram', () => {
  render(<VkNativeWorkspace />)
  fireEvent.click(screen.getByRole('button', { name: 'Сервисы' }))
  fireEvent.click(screen.getByRole('button', { name: 'Нативные партнёры' }))
  expect(screen.getByTestId('native-content')).toHaveTextContent('profile')
  expect(screen.getByRole('button', { name: 'Профиль' })).toHaveAttribute('aria-current', 'page')
})
