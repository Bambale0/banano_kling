import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { useApp } from '@/lib/app-context'
import { TabNav } from '../tab-nav'
import { TabContent } from '../tab-content'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('next/dynamic', () => () => () => <p>Lazy tab</p>)
jest.mock('../tabs/studio-tab', () => ({ StudioTab: () => <p>Studio tab</p> }))

beforeEach(() => {
  jest.mocked(useApp).mockReturnValue({ activeTab: 0, setActiveTab: jest.fn() } as unknown as ReturnType<typeof useApp>)
})
afterEach(() => {
  window.history.replaceState({}, '', '/')
  delete process.env.NEXT_PUBLIC_MINIAPP_PLATFORM
  jest.resetAllMocks()
})

test('VK signed app hides Motion but preserves other shared tab identifiers', () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001')
  render(<TabNav />)
  expect(screen.queryByRole('button', { name: 'Motion' })).not.toBeInTheDocument()
  for (const label of ['Студия', 'Тренды', 'Фото', 'Видео', 'Лента', 'Сервисы', 'Профиль']) {
    expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
  }
})

test('Telegram retains Motion and all eight original tabs', () => {
  render(<TabNav />)
  expect(screen.getByRole('button', { name: 'Motion' })).toBeInTheDocument()
  expect(screen.getAllByRole('button')).toHaveLength(8)
})

test('VK stale Motion selection is redirected to Video rather than mounting Motion', () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001')
  const setActiveTab = jest.fn()
  jest.mocked(useApp).mockReturnValue({ activeTab: 3, setActiveTab } as unknown as ReturnType<typeof useApp>)
  render(<TabContent />)
  expect(setActiveTab).toHaveBeenCalledWith(2)
})

test('Telegram Motion selection is not redirected', () => {
  const setActiveTab = jest.fn()
  jest.mocked(useApp).mockReturnValue({ activeTab: 3, setActiveTab } as unknown as ReturnType<typeof useApp>)
  render(<TabContent />)
  expect(setActiveTab).not.toHaveBeenCalled()
})
