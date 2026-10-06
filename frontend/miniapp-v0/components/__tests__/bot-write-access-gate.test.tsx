import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { BotWriteAccessGate } from '@/components/bot-write-access-gate'
import { confirmTelegramWriteAccess } from '@/lib/api'

jest.mock('lucide-react', () => {
  const Icon = (props: React.SVGProps<SVGSVGElement>) => <svg {...props} />
  return { ExternalLink: Icon, LoaderCircle: Icon, MessageCircle: Icon }
})

jest.mock('@/lib/api', () => ({
  confirmTelegramWriteAccess: jest.fn(),
}))

const confirmAccess = confirmTelegramWriteAccess as jest.MockedFunction<typeof confirmTelegramWriteAccess>

describe('BotWriteAccessGate', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    ;(window.Telegram!.WebApp as any).requestWriteAccess = undefined
    ;(window.Telegram!.WebApp as any).openTelegramLink = jest.fn()
  })

  it('does not render when bot delivery is already available', () => {
    render(
      <BotWriteAccessGate
        required={false}
        botUsername="neuromix_bot"
        onRefresh={jest.fn()}
      />,
    )

    expect(screen.queryByText('Разреши боту писать тебе')).toBeNull()
  })

  it('requests native write access and confirms it on the backend', async () => {
    const onRefresh = jest.fn().mockResolvedValue(undefined)
    ;(window.Telegram!.WebApp as any).requestWriteAccess = jest.fn((callback: (allowed: boolean) => void) => callback(true))
    confirmAccess.mockResolvedValue({
      ok: true,
      chat_available: true,
      confirmation_sent: true,
      needs_bot_start: false,
    })

    render(
      <BotWriteAccessGate
        required
        botUsername="neuromix_bot"
        onRefresh={onRefresh}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Разрешить' }))

    await waitFor(() => expect(confirmAccess).toHaveBeenCalledTimes(1))
    expect(onRefresh).toHaveBeenCalledTimes(1)
    expect((window.Telegram!.WebApp as any).openTelegramLink).not.toHaveBeenCalled()
  })

  it('opens the bot deep link when native write access is unavailable', () => {
    render(
      <BotWriteAccessGate
        required
        botUsername="neuromix_bot"
        onRefresh={jest.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Разрешить' }))

    expect((window.Telegram!.WebApp as any).openTelegramLink).toHaveBeenCalledWith(
      'https://t.me/neuromix_bot?start=miniapp_delivery',
    )
    expect(screen.getByText(/нажми Start/i)).toBeTruthy()
  })
})
