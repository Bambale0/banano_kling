import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { useApp } from '@/lib/app-context'
import { ASTRO_TAB_ID, effectiveTabId, isAstroVisible } from '@/lib/astro-access'
import { TabNav } from '../tab-nav'

jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))

const mockedUseApp = jest.mocked(useApp)

function renderNavigation(isAdmin: boolean, mode: 'live' | 'locked' = 'live') {
  const setActiveTab = jest.fn()
  mockedUseApp.mockReturnValue({
    state: { mode, user: { isAdmin } },
    activeTab: 0,
    setActiveTab,
  } as unknown as ReturnType<typeof useApp>)
  render(<TabNav />)
  return setActiveTab
}

describe('Astro administrator-only preview', () => {
  afterEach(() => jest.clearAllMocks())

  it('does not show Astro for a regular Telegram or VK user and preserves Motion', () => {
    const setActiveTab = renderNavigation(false)
    expect(screen.queryByRole('button', { name: 'Астро' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Motion' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Motion' }))
    expect(setActiveTab).toHaveBeenCalledWith(3)
  })

  it('shows Astro in the same slot for an authenticated admin', () => {
    const setActiveTab = renderNavigation(true)
    expect(screen.queryByRole('button', { name: 'Motion' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Астро' }))
    expect(setActiveTab).toHaveBeenCalledWith(ASTRO_TAB_ID)
  })

  it('does not expose Astro during locked/bootstrap state', () => {
    renderNavigation(true, 'locked')
    expect(screen.queryByRole('button', { name: 'Астро' })).not.toBeInTheDocument()
  })

  it('denies an injected Astro tab id after privilege loss', () => {
    const ordinary = { mode: 'live' as const, user: { isAdmin: false } }
    const admin = { mode: 'live' as const, user: { isAdmin: true } }
    const lockedAdmin = { mode: 'locked' as const, user: { isAdmin: true } }
    expect(isAstroVisible(ordinary)).toBe(false)
    expect(isAstroVisible(admin)).toBe(true)
    expect(isAstroVisible(lockedAdmin)).toBe(false)
    expect(effectiveTabId(ASTRO_TAB_ID, ordinary)).toBe(0)
    expect(effectiveTabId(ASTRO_TAB_ID, admin)).toBe(ASTRO_TAB_ID)
    expect(effectiveTabId(3, ordinary)).toBe(3)
  })
})
