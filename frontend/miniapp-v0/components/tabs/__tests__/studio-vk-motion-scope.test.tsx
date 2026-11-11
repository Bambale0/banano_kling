import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { useApp } from '@/lib/app-context'
import { StudioTab } from '../studio-tab'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('../../quick-action-grid', () => ({ QuickActionGrid: ({ onMotionClick }: { onMotionClick: () => void }) =>
  <button onClick={onMotionClick}>Оживить</button> }))
jest.mock('../../task-history-list', () => ({ TaskHistoryList: () => null }))
jest.mock('../../genjutsu-entry', () => ({ GenjutsuButton: () => null }))

const setActiveTab = jest.fn()
beforeEach(() => {
  jest.mocked(useApp).mockReturnValue({ setActiveTab, openBalance: jest.fn(), openWorkspace: jest.fn() } as unknown as ReturnType<typeof useApp>)
})
afterEach(() => {
  setActiveTab.mockReset()
  window.history.replaceState({}, '', '/')
  delete process.env.NEXT_PUBLIC_MINIAPP_PLATFORM
})

test('VK Studio quick action Оживить opens the Video workflow, never Motion', () => {
  window.history.replaceState({}, '', '/?vk_app_id=123&vk_user_id=2001')
  render(<StudioTab />)
  fireEvent.click(screen.getByRole('button', { name: 'Оживить' }))
  expect(setActiveTab).toHaveBeenCalledWith(2)
  expect(setActiveTab).not.toHaveBeenCalledWith(3)
})

test('Telegram Studio quick action Оживить keeps the Motion workflow', () => {
  render(<StudioTab />)
  fireEvent.click(screen.getByRole('button', { name: 'Оживить' }))
  expect(setActiveTab).toHaveBeenCalledWith(3)
})
