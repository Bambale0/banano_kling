import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { PartnerApprovalSheet } from '@/components/partner-approval-sheet'
import { executeMiniAppAction, fetchPartnerOverview } from '@/lib/api'
import { useApp } from '@/lib/app-context'

jest.mock('lucide-react', () => {
  const Icon = (props: React.SVGProps<SVGSVGElement>) => <svg {...props} />
  return {
    BriefcaseBusiness: Icon,
    CheckCircle2: Icon,
    Copy: Icon,
    Loader2: Icon,
    RefreshCw: Icon,
    Send: Icon,
    ShieldCheck: Icon,
    XCircle: Icon,
  }
})

jest.mock('@/lib/api', () => ({
  executeMiniAppAction: jest.fn(),
  fetchPartnerOverview: jest.fn(),
}))

jest.mock('@/lib/app-context', () => ({
  useApp: jest.fn(),
}))

jest.mock('@/components/ui/sheet', () => ({
  Sheet: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  SheetDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
}))

jest.mock('@/components/ui/button', () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
}))

const mockedUseApp = useApp as jest.MockedFunction<typeof useApp>
const mockedFetchPartnerOverview = fetchPartnerOverview as jest.MockedFunction<typeof fetchPartnerOverview>
const mockedExecuteMiniAppAction = executeMiniAppAction as jest.MockedFunction<typeof executeMiniAppAction>

const overview = (status = 'partner') => ({
  is_partner: status === 'partner', referrals_count: 12, balance_rub: 345.5,
  prompt_repeat_balance_rub: 0, prompt_repeat_total_rub: 0, channel_url: '',
  referral_link: 'https://t.me/example_bot?start=ref_TESTCODE',
  percent: 30, level2_percent: 7, status,
})

describe('PartnerApprovalSheet', () => {
  beforeEach(() => {
    jest.resetAllMocks()
    mockedUseApp.mockReturnValue({ activeWorkspace: 'partners', closeWorkspace: jest.fn() } as unknown as ReturnType<typeof useApp>)
  })

  it.each(['available', 'pending', 'rejected', 'approved', 'partner'])(
    'opens the cabinet without an application for historical status %s', async (status) => {
      mockedFetchPartnerOverview.mockResolvedValue(overview(status))
      render(<PartnerApprovalSheet />)
      expect(await screen.findByText('Ваш партнёрский кабинет')).toBeTruthy()
      expect(screen.getByText(overview().referral_link)).toBeTruthy()
      expect(screen.getByText(/1 уровня: 30%/)).toBeTruthy()
      expect(screen.getByRole('button', { name: /скопировать ссылку/i })).toBeTruthy()
      expect(screen.queryByRole('button', { name: /активировать|подать заявку/i })).toBeNull()
      expect(mockedExecuteMiniAppAction).not.toHaveBeenCalled()
    },
  )

  it.each([0, 30, 40])('uses the server-provided individual commission %s without fallback', async (percent) => {
    mockedFetchPartnerOverview.mockResolvedValue({ ...overview(), percent })
    render(<PartnerApprovalSheet />)
    expect(await screen.findByText(new RegExp(`1 уровня: ${percent}%`))).toBeTruthy()
    expect(screen.getByText(/2 уровня: 7%/)).toBeTruthy()
  })

  it('shows an error and retries without offering activation', async () => {
    mockedFetchPartnerOverview.mockRejectedValueOnce(new Error('Telegram auth failed')).mockResolvedValueOnce(overview())
    render(<PartnerApprovalSheet />)
    expect((await screen.findByRole('alert')).textContent).toContain('Telegram auth failed')
    expect(screen.queryByText('Ваш партнёрский кабинет')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку' }))
    expect(await screen.findByText('Ваш партнёрский кабинет')).toBeTruthy()
    expect(mockedFetchPartnerOverview).toHaveBeenCalledTimes(2)
    expect(mockedExecuteMiniAppAction).not.toHaveBeenCalled()
  })

  it('refreshes the current data without submitting applications', async () => {
    mockedFetchPartnerOverview.mockResolvedValueOnce(overview()).mockResolvedValueOnce({ ...overview(), referrals_count: 23 })
    render(<PartnerApprovalSheet />)
    await screen.findByText('Ваш партнёрский кабинет')
    fireEvent.click(screen.getByRole('button', { name: 'Обновить' }))
    expect(await screen.findByText('23')).toBeTruthy()
    expect(mockedExecuteMiniAppAction).not.toHaveBeenCalled()
  })

  it('ignores an interrupted request after closing and reopening', async () => {
    let finishOld!: (data: ReturnType<typeof overview>) => void
    mockedFetchPartnerOverview.mockReturnValueOnce(new Promise((resolve) => { finishOld = resolve }))
      .mockResolvedValueOnce({ ...overview(), referrals_count: 42 })
    const { rerender } = render(<PartnerApprovalSheet />)
    await waitFor(() => expect(mockedFetchPartnerOverview).toHaveBeenCalledTimes(1))
    mockedUseApp.mockReturnValue({ activeWorkspace: null, closeWorkspace: jest.fn() } as unknown as ReturnType<typeof useApp>)
    rerender(<PartnerApprovalSheet />)
    mockedUseApp.mockReturnValue({ activeWorkspace: 'partners', closeWorkspace: jest.fn() } as unknown as ReturnType<typeof useApp>)
    rerender(<PartnerApprovalSheet />)
    expect(await screen.findByText('42')).toBeTruthy()
    await act(async () => { finishOld({ ...overview(), referrals_count: 99 }) })
    expect(screen.getByText('42')).toBeTruthy()
    expect(screen.queryByText('99')).toBeNull()
  })

  it('disables copying while the server has no referral link', async () => {
    mockedFetchPartnerOverview.mockResolvedValue({ ...overview(), referral_link: '' })
    render(<PartnerApprovalSheet />)
    expect(await screen.findByText('Ссылка временно недоступна')).toBeTruthy()
    expect((screen.getByRole('button', { name: /скопировать ссылку/i }) as HTMLButtonElement).disabled).toBe(true)
    expect(mockedExecuteMiniAppAction).not.toHaveBeenCalled()
  })
})
