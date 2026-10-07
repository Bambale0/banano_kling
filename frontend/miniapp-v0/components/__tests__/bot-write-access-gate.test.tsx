import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BotWriteAccessGate } from '@/components/bot-write-access-gate'
import { getStartParamFallback } from '@/lib/api'

jest.mock('lucide-react', () => {
  const Icon = (props: React.SVGProps<SVGSVGElement>) => <svg {...props} />
  return { ExternalLink: Icon, LoaderCircle: Icon, MessageCircle: Icon }
})
jest.mock('@/lib/api', () => ({ getStartParamFallback: jest.fn(() => '') }))
const startParam = getStartParamFallback as jest.Mock
const webApp = () => window.Telegram!.WebApp as any
const open = () => fireEvent.click(screen.getByRole('button', { name: 'Открыть бота' }))
const check = () => fireEvent.click(screen.getByRole('button', { name: 'Проверить снова' }))

describe('BotWriteAccessGate', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    window.sessionStorage.clear()
    startParam.mockReturnValue('')
    webApp().requestWriteAccess = jest.fn()
    webApp().openTelegramLink = jest.fn()
    webApp().onEvent = jest.fn()
    webApp().offEvent = jest.fn()
  })
  afterEach(() => jest.useRealTimers())

  it('does not render for confirmed delivery', () => {
    render(<BotWriteAccessGate required={false} botUsername="neuromix_bot" onRefresh={jest.fn()} />)
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('opens Start immediately even if native permission never returns, without confirming access', () => {
    const refresh = jest.fn()
    render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={refresh} />)
    open()
    expect(webApp().openTelegramLink).toHaveBeenCalledWith('https://t.me/neuromix_bot?start=miniapp_delivery')
    expect(webApp().requestWriteAccess).not.toHaveBeenCalled()
    expect(refresh).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Открыть бота' })).toBeEnabled()
  })

  it.each([
    ['ref_PARTNER', 'ref_PARTNER'],
    ['feed_42_ref_PARTNER', 'ref_PARTNER'],
    ['prompt_42_ref_PARTNER', 'ref_PARTNER'],
    ['posts_AUTHOR_ref_PARTNER', 'ref_PARTNER'],
    ['profile_AUTHOR', 'ref_AUTHOR'],
    ['success_order42', 'miniapp_delivery'],
    ['task_private', 'miniapp_delivery'],
    ['ref_' + 'A'.repeat(61), 'miniapp_delivery'],
  ])('preserves safe referral for %s without replaying actions', (launch, expected) => {
    startParam.mockReturnValue(launch)
    render(<BotWriteAccessGate required botUsername="@neuromix_bot" onRefresh={jest.fn()} />)
    open()
    expect(webApp().openTelegramLink).toHaveBeenCalledWith('https://t.me/neuromix_bot?start=' + expected)
  })

  it('keeps the gate until the server confirms Start and supports manual retry', async () => {
    const refresh = jest.fn().mockResolvedValue(false)
    render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={refresh} />)
    check()
    await waitFor(() => expect(screen.getByText(/Доступ пока не подтверждён/)).toBeTruthy())
    expect(screen.getByRole('dialog')).toBeTruthy()
    check()
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(2))
  })

  it.each(['focus', 'visibilitychange', 'activated'])('verifies on %s after opening bot', async (event) => {
    const refresh = jest.fn().mockResolvedValue(false)
    render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={refresh} />)
    open()
    if (event === 'activated') act(() => webApp().onEvent.mock.calls.find((call: any[]) => call[0] === 'activated')[1]())
    else fireEvent(event === 'focus' ? window : document, new Event(event))
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
    expect(refresh.mock.calls[0][0]).toBeInstanceOf(AbortSignal)
  })

  it('expires a hung check, aborts its request, and ignores its late result', async () => {
    jest.useFakeTimers()
    let resolve!: (value: boolean) => void
    const refresh = jest.fn().mockImplementationOnce(() => new Promise<boolean>(done => { resolve = done })).mockResolvedValue(false)
    render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={refresh} />)
    check()
    expect(screen.getByRole('button', { name: 'Открыть бота' })).toBeEnabled()
    await act(async () => { jest.advanceTimersByTime(12_000) })
    expect(refresh.mock.calls[0][0].aborted).toBe(true)
    expect(screen.getByText(/Не удалось проверить доступ/)).toBeTruthy()
    check()
    await act(async () => {})
    expect(screen.getByText(/Доступ пока не подтверждён/)).toBeTruthy()
    await act(async () => resolve(true))
    expect(screen.getByText(/Доступ пока не подтверждён/)).toBeTruthy()
  })

  it('deduplicates simultaneous return events and aborts on opening bot again', async () => {
    const refresh = jest.fn((_signal: AbortSignal) => new Promise<boolean>(() => {}))
    render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={refresh} />)
    open()
    fireEvent.focus(window)
    fireEvent(document, new Event('visibilitychange'))
    expect(refresh).toHaveBeenCalledTimes(1)
    open()
    expect(refresh.mock.calls[0][0].aborted).toBe(true)
    expect(screen.getByRole('button', { name: 'Проверить снова' })).toBeEnabled()
  })

  it('cancels when server state removes the gate and cleans event handlers', () => {
    const refresh = jest.fn((_signal: AbortSignal) => new Promise<boolean>(() => {}))
    const view = render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={refresh} />)
    check()
    view.rerender(<BotWriteAccessGate required={false} botUsername="neuromix_bot" onRefresh={refresh} />)
    expect(refresh.mock.calls[0][0].aborted).toBe(true)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(webApp().offEvent).toHaveBeenCalledWith('activated', expect.any(Function))
  })

  it('recovers from a rejected check and leaves bot navigation available', async () => {
    render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={jest.fn().mockRejectedValue(new Error('403'))} />)
    check()
    await waitFor(() => expect(screen.getByText(/Не удалось проверить доступ/)).toBeTruthy())
    open()
    expect(webApp().openTelegramLink).toHaveBeenCalledTimes(1)
  })

  it('does not navigate to malformed or missing bot usernames', () => {
    render(<BotWriteAccessGate required botUsername="bad/name?token=x" onRefresh={jest.fn()} />)
    open()
    expect(webApp().openTelegramLink).not.toHaveBeenCalled()
    expect(screen.getByText(/Не удалось проверить доступ/)).toBeTruthy()
  })
})


it('a reappearing gate has an enabled check instead of stale loading', () => {
  const refresh = jest.fn((_signal: AbortSignal) => new Promise<boolean>(() => {}))
  const view = render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={refresh} />)
  check()
  view.rerender(<BotWriteAccessGate required={false} botUsername="neuromix_bot" onRefresh={refresh} />)
  view.rerender(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={refresh} />)
  expect(screen.getByRole('button', { name: 'Проверить снова' })).toBeEnabled()
})

it('uses browser navigation when Telegram link API is unavailable', () => {
  webApp().openTelegramLink = undefined
  const windowOpen = jest.spyOn(window, 'open').mockReturnValue(null)
  render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={jest.fn()} />)
  open()
  expect(windowOpen).toHaveBeenCalledWith('https://t.me/neuromix_bot?start=miniapp_delivery', '_blank', 'noopener,noreferrer')
  windowOpen.mockRestore()
})


describe('optional delivery offer', () => {
  beforeEach(() => { window.sessionStorage.clear(); startParam.mockReturnValue(''); webApp().openTelegramLink = jest.fn() })
  it('skips without granting access or starting requests and stays dismissed on remount', () => {
    const refresh = jest.fn()
    const view = render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={refresh} />)
    fireEvent.click(screen.getByRole('button', { name: 'Пропустить' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByText('Результаты доступны в Студии')).toBeTruthy()
    fireEvent.focus(window)
    expect(refresh).not.toHaveBeenCalled()
    expect(webApp().openTelegramLink).not.toHaveBeenCalled()
    view.unmount()
    render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={refresh} />)
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Получать в боте' }))
    expect(screen.getByRole('dialog')).toBeTruthy()
    open()
    expect(webApp().openTelegramLink).toHaveBeenCalledWith('https://t.me/neuromix_bot?start=miniapp_delivery')
  })
  it('skip cancels a pending check and late success cannot reopen the offer', async () => {
    let resolve!: (value: boolean) => void
    const refresh = jest.fn((_signal: AbortSignal) => new Promise<boolean>(done => { resolve = done }))
    render(<BotWriteAccessGate required botUsername="neuromix_bot" onRefresh={refresh} />)
    check()
    fireEvent.click(screen.getByRole('button', { name: 'Пропустить' }))
    expect(refresh.mock.calls[0][0].aborted).toBe(true)
    await act(async () => resolve(true))
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
