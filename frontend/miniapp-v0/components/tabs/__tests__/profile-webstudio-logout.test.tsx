import { render, screen, waitFor } from '@testing-library/react'
import { ProfileTab } from '../profile-tab'
import { useApp } from '@/lib/app-context'
import { fetchMyFeed, fetchPartnerOverview } from '@/lib/api'
jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({
  ...jest.requireActual('@/lib/api'),
  fetchMyFeed: jest.fn(),
  fetchProfileFeed: jest.fn(),
  fetchPartnerOverview: jest.fn(),
}))
jest.mock('@/components/personal-reference-library', () => ({
  PersonalReferenceLibrary: () => null,
}))
jest.mock('@/components/shared-account-preview', () => ({
  SharedAccountPreview: () => null,
}))
const mockedApp = useApp as jest.Mock
const mockedMyFeed = fetchMyFeed as jest.Mock
const mockedStats = fetchPartnerOverview as jest.Mock
const fakeState = {
  mode: 'live',
  user: {
    telegramId: 424242, username: 'webstudio', firstName: 'Web',
    lastName: 'Account', credits: 100, isAdmin: false, referralCode: '',
    photoUrl: '', channelUrl: '', botUsername: 'neuromixx_bot',
    promptRepeatBalanceRub: 0, promptRepeatTotalRub: 0,
  },
  recentTasks: [], videoModels: [], imageModels: [],
}
beforeEach(() => {
  jest.clearAllMocks()
  window.sessionStorage.clear()
  window.history.replaceState({}, '', '/mini-app/')
  window.Telegram = undefined
  delete window.__BANANO_BROWSER_SIGNOUT__
  delete window.__BANANO_PLATFORM_INIT_DATA__
  delete window.__BANANO_TG_INIT_DATA__
  mockedMyFeed.mockResolvedValue([])
  mockedStats.mockResolvedValue({ prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0 })
  mockedApp.mockReturnValue({
    state: fakeState, viewedProfileCode: null, feedDeepLink: null,
    consumeFeedDeepLink: jest.fn(), setActiveTab: jest.fn(),
    setPromptPreset: jest.fn(), setVideoPromptPreset: jest.fn(),
  })
})
it('renders webstudio logout on the own profile', async () => {
  window.__BANANO_TG_INIT_DATA__ = 'query_id=webstudio_' + 'w'.repeat(32) + '&auth_date=1795100000&hash=test'
  render(<ProfileTab />)
  expect(await screen.findByRole('button', { name: 'Выйти из аккаунта' })).toBeTruthy()
})
it('never renders a website logout in native Telegram', async () => {
  window.__BANANO_TG_INIT_DATA__ = 'query_id=AAE123&auth_date=1795100000&hash=test'
  render(<ProfileTab />)
  await waitFor(() => expect(mockedMyFeed).toHaveBeenCalled())
  expect(screen.queryByRole('button', { name: 'Выйти из аккаунта' })).toBeNull()
})
