import '@testing-library/jest-dom'
import { act, render, screen } from '@testing-library/react'
import { GenjutsuEntry } from '../genjutsu-entry'
import { getStartParamFallback } from '@/lib/api'

jest.mock('@/lib/api', () => ({
  getStartParamFallback: jest.fn(),
}))

jest.mock('@/lib/genjutsu-api', () => ({
  genjutsuCall: jest.fn(),
  openGenjutsu: jest.fn(),
}))

jest.mock('../genjutsu-studio', () => ({
  GenjutsuStudio: ({ initial }: { initial: { admin?: boolean } }) => (
    <div data-testid="genjutsu-studio">{initial.admin ? 'ADMIN_OPEN' : 'USER_OPEN'}</div>
  ),
}))

const startParam = getStartParamFallback as jest.MockedFunction<typeof getStartParamFallback>

beforeEach(() => {
  jest.clearAllMocks()
  window.history.replaceState({}, '', '/mini-app/')
})

test('genjutsu_admin start parameter opens the management surface', async () => {
  startParam.mockReturnValue('genjutsu_admin')
  render(<GenjutsuEntry />)
  expect(await screen.findByText('ADMIN_OPEN')).toBeInTheDocument()
})

test('normal genjutsu start parameter keeps the user editor', async () => {
  startParam.mockReturnValue('genjutsu')
  render(<GenjutsuEntry />)
  expect(await screen.findByText('USER_OPEN')).toBeInTheDocument()
})


test('mobile Genjutsu opens edge-to-edge without horizontal dialog overflow', async () => {
  startParam.mockReturnValue('genjutsu')
  render(<GenjutsuEntry />)
  await screen.findByText('USER_OPEN')
  const dialog = document.querySelector('[data-slot="dialog-content"]')
  expect(dialog).not.toBeNull()
  expect(dialog?.className).toContain('w-screen')
  expect(dialog?.className).toContain('max-w-none')
  expect(dialog?.className).toContain('overflow-x-hidden')
  expect(dialog?.className).toContain('rounded-none')
})


test.each(['start', 'query'])('published recipe %s links are owned by the preview router', async (kind) => {
  const id = 'a'.repeat(32)
  startParam.mockReturnValue(kind === 'start' ? 'genjutsu_recipe_' + id : '')
  if (kind === 'query') window.history.replaceState({}, '', '/mini-app/?genjutsu=1&genjutsu_recipe=' + id)
  render(<GenjutsuEntry />)
  expect(screen.queryByTestId('genjutsu-studio')).not.toBeInTheDocument()
})


test('history navigation dismisses a recipe even when the child cannot handle close', async () => {
  startParam.mockReturnValue('')
  render(<GenjutsuEntry />)
  act(() => window.dispatchEvent(new CustomEvent('genjutsu:open', { detail: { recipe_id: 'a'.repeat(32) } })))
  await screen.findByTestId('genjutsu-studio')
  // The mock deliberately has no request-close listener, just like a pending
  // lazy chunk or a Studio that is busy and cannot save/close right now.
  act(() => window.dispatchEvent(new Event('genjutsu:history-navigation')))
  expect(screen.queryByTestId('genjutsu-studio')).not.toBeInTheDocument()
})

test('history recipe dismissal leaves owned editor/admin session contracts unchanged', async () => {
  startParam.mockReturnValue('genjutsu_admin')
  render(<GenjutsuEntry />)
  await screen.findByText('ADMIN_OPEN')
  act(() => window.dispatchEvent(new Event('genjutsu:history-navigation')))
  expect(screen.getByText('ADMIN_OPEN')).toBeInTheDocument()
})
