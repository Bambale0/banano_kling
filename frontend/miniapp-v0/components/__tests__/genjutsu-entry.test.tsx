import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
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
