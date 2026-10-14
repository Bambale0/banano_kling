import '@testing-library/jest-dom'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { FeedTab } from '@/components/tabs/feed-tab'
import { useApp } from '@/lib/app-context'
import { fetchFeed, shareFeedItem } from '@/lib/api'
jest.mock('@/lib/app-context', () => ({ useApp: jest.fn() }))
jest.mock('@/lib/api', () => ({
 addFeedComment: jest.fn(), fetchFeed: jest.fn(), fetchFeedComments: jest.fn(),
 likeFeedItem: jest.fn(), removeFeedItem: jest.fn(), setFeedItemBlurred: jest.fn(), shareFeedItem: jest.fn(),
}))
const item = {
 id: 55, task_id: 'fixture', model: 'genjutsu', gen_type: 'video', result_url: 'https://example.test/video.mp4',
 preview_url: 'https://example.test/video.mp4', result_urls: [], prompt: 'PRIVATE_RECIPE',
 likes_count: 0, shares_count: 0, comments_count: 0, reference_images: [], reference_videos: [],
 references_hidden: true, prompt_hidden: true, author: 'Fixture', remixes: 0, created_at: '2026-10-08',
}
const link = 'https://t.me/fixture_bot?start=feed_55_ref_EXACT%2Bcode'
const writeText = jest.fn()
const execCopy = jest.fn()
const scrollRecovery = jest.fn()
beforeEach(() => {
 jest.clearAllMocks()
 window.Telegram!.WebApp!.openTelegramLink = jest.fn()
 Object.defineProperty(window.Telegram!.WebApp!, 'platform', { configurable: true, value: 'web' })
 Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: scrollRecovery })
 Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
 Object.defineProperty(document, 'execCommand', { configurable: true, value: execCopy })
 writeText.mockRejectedValue(new DOMException('Denied', 'NotAllowedError'))
 execCopy.mockReturnValue(false)
 ;(useApp as jest.Mock).mockReturnValue({
 state: { mode: 'live', user: { isAdmin: false }, imageModels: [], videoModels: [] },
 feedDeepLink: null, consumeFeedDeepLink: jest.fn(), setActiveTab: jest.fn(),
 setPromptPreset: jest.fn(), setVideoPromptPreset: jest.fn(), openProfile: jest.fn(),
 })
 ;(fetchFeed as jest.Mock).mockResolvedValue({ feed: [item], models: [] })
 ;(shareFeedItem as jest.Mock).mockResolvedValue({ item, link })
})
async function share() {
 render(<FeedTab />)
 const button = await screen.findByRole('button', { name: 'Ссылка' })
 await act(async () => { fireEvent.click(button) })
}
it('retains the exact server link when both clipboard methods fail; retries on a fresh click without another API request', async () => {
 await share()
 const field = await screen.findByRole('textbox', { name: 'Ссылка на публикацию' })
 expect(field).toHaveValue(link)
 expect(screen.queryByText('PRIVATE_RECIPE')).not.toBeInTheDocument()
 await screen.findByText(/Telegram не разрешил запись в буфер/)
 expect(scrollRecovery).toHaveBeenCalledWith({ block: 'center' })
 writeText.mockResolvedValueOnce(undefined)
 const previous = writeText.mock.calls.length
 fireEvent.click(screen.getByRole('button', { name: 'Скопировать ссылку' }))
 // Clipboard is invoked synchronously in this fresh event, before any await.
 expect(writeText.mock.calls.length).toBe(previous + 1)
 expect(await screen.findByText('Ссылка скопирована')).toBeInTheDocument()
 expect(screen.queryByText(/Telegram не разрешил запись в буфер/)).not.toBeInTheDocument()
 expect(shareFeedItem).toHaveBeenCalledTimes(1)
 expect(writeText).toHaveBeenLastCalledWith(link)
})
it('keeps one-tap success and reports it', async () => {
 writeText.mockResolvedValue(undefined)
 await share()
 expect(await screen.findByText('Ссылка скопирована')).toBeInTheDocument()
 expect(execCopy).not.toHaveBeenCalled()
})
it('distinguishes API failure, then clears stale failure after a successful retry', async () => {
 ;(shareFeedItem as jest.Mock).mockRejectedValueOnce(new Error('Сервис временно недоступен'))
 await share()
 expect(await screen.findByText('Сервис временно недоступен')).toBeInTheDocument()
 expect(screen.queryByRole('textbox', { name: 'Ссылка на публикацию' })).not.toBeInTheDocument()
 expect(writeText).not.toHaveBeenCalled()
 writeText.mockResolvedValue(undefined)
 fireEvent.click(screen.getByRole('button', { name: 'Ссылка' }))
 await screen.findByText('Ссылка скопирована')
 expect(screen.queryByText('Сервис временно недоступен')).not.toBeInTheDocument()
})
it('leaves manual selection available after repeated denied copy attempts', async () => {
 await share()
 const field = await screen.findByRole('textbox', { name: 'Ссылка на публикацию' })
 fireEvent.click(screen.getByRole('button', { name: 'Скопировать ссылку' }))
 await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2))
 expect(field).toHaveValue(link)
 expect(shareFeedItem).toHaveBeenCalledTimes(1)
 fireEvent.focus(field)
 expect((field as HTMLInputElement).selectionStart).toBe(0)
 expect((field as HTMLInputElement).selectionEnd).toBe(link.length)
})

it.each([
 'https://t.me/fixture_bot?start=remix_55_ref_EXACT%2Bcode',
 'https://t.me/fixture_bot/app?startapp=remix_55_ref_EXACT%2Bcode&mode=compact',
])('opens the unchanged server URL through Telegram on an explicit click: %s', async (exactLink) => {
 const openTelegramLink = jest.fn()
 window.Telegram!.WebApp!.openTelegramLink = openTelegramLink
 ;(shareFeedItem as jest.Mock).mockResolvedValueOnce({ item, link: exactLink })
 await share()
 const open = await screen.findByRole('link', { name: 'Открыть ссылку' })
 expect(open).toHaveAttribute('href', exactLink)
 expect(open).toHaveAttribute('target', '_blank')
 expect(open).toHaveAttribute('rel', 'noopener noreferrer')
 expect(openTelegramLink).not.toHaveBeenCalled()
 const copyCalls = writeText.mock.calls.length
 expect(fireEvent.click(open)).toBe(false)
 expect(openTelegramLink).toHaveBeenCalledWith(exactLink)
 expect(fireEvent.click(open)).toBe(false)
 expect(openTelegramLink).toHaveBeenCalledTimes(2)
 expect(shareFeedItem).toHaveBeenCalledTimes(1)
 expect(writeText).toHaveBeenCalledTimes(copyCalls)
 expect(screen.getByRole('textbox', { name: 'Ссылка на публикацию' })).toHaveValue(exactLink)
})

it.each(['absent', 'throws', 'web-url', 'modified-click'])('keeps normal secure browser navigation for %s', async (mode) => {
 const openTelegramLink = jest.fn(() => { if (mode === 'throws') throw new Error('SDK unavailable') })
 window.Telegram!.WebApp!.openTelegramLink = mode === 'absent' ? undefined : openTelegramLink
 const exactLink = mode === 'web-url' ? 'https://example.test/post?startapp=feed_55_ref_EXACT%2Bcode' : link
 ;(shareFeedItem as jest.Mock).mockResolvedValueOnce({ item, link: exactLink })
 await share()
 const open = await screen.findByRole('link', { name: 'Открыть ссылку' })
 expect(open).toHaveAttribute('href', exactLink)
 expect(fireEvent.click(open, mode === 'modified-click' ? { ctrlKey: true } : {})).toBe(true)
 expect(openTelegramLink).toHaveBeenCalledTimes(mode === 'throws' ? 1 : 0)
 expect(shareFeedItem).toHaveBeenCalledTimes(1)
})

it.each(['javascript:alert(1)', 'data:text/html,unsafe', '//t.me/fixture_bot', 'https://user:password@t.me/fixture_bot', 'https://t.me/fixture_bot\n?start=unsafe'])('keeps an unsafe URL non-executable: %s', async (unsafe) => {
 ;(shareFeedItem as jest.Mock).mockResolvedValueOnce({ item, link: unsafe })
 await share()
 expect(screen.queryByRole('link', { name: 'Открыть ссылку' })).not.toBeInTheDocument()
 expect(screen.getByRole('textbox', { name: 'Ссылка на публикацию' })).toHaveValue(unsafe.replace(/\n/g, ''))
})

it('iOS Telegram exposes a fresh-tap copy action and selects the visible URL synchronously', async () => {
 Object.defineProperty(window.Telegram!.WebApp!, 'platform', { configurable: true, value: 'ios' })
 execCopy.mockImplementation(() => {
   const field = screen.getByRole('textbox', { name: 'Ссылка на публикацию' }) as HTMLInputElement
   expect(document.activeElement).toBe(field)
   expect(field.selectionStart).toBe(0)
   expect(field.selectionEnd).toBe(link.length)
   return true
 })
 await share()
 expect(await screen.findByText(/Ссылка готова/)).toBeInTheDocument()
 expect(writeText).not.toHaveBeenCalled() // never try auto-copy after fetching the URL
 expect(execCopy).not.toHaveBeenCalled()
 const retry = screen.getByRole('button', { name: 'Скопировать ссылку' })
 fireEvent.click(retry)
 expect(execCopy).toHaveBeenCalledTimes(1) // inside the user's fresh tap
 expect(writeText).not.toHaveBeenCalled()
 expect(await screen.findByText('Ссылка скопирована')).toBeInTheDocument()
 expect(shareFeedItem).toHaveBeenCalledTimes(1)
})

it('provides a native Telegram share-sheet fallback with the exact encoded remix URL', async () => {
 await share()
 const forwarded = screen.getByRole('link', { name: 'Поделиться в Telegram' })
 const native = 'https://t.me/share/url?url=' + encodeURIComponent(link)
 expect(forwarded).toHaveAttribute('href', native)
 expect(new URL(forwarded.getAttribute('href')!).searchParams.get('url')).toBe(link)
 expect(forwarded).toHaveAttribute('rel', 'noopener noreferrer')
 expect(fireEvent.click(forwarded)).toBe(false)
 expect(window.Telegram!.WebApp!.openTelegramLink).toHaveBeenCalledWith(native)
 expect(shareFeedItem).toHaveBeenCalledTimes(1)
})

it('never exposes the share-sheet action for a non-web unsafe deep link', async () => {
 ;(shareFeedItem as jest.Mock).mockResolvedValueOnce({ item, link: 'javascript:alert(1)' })
 await share()
 expect(screen.queryByRole('link', { name: 'Поделиться в Telegram' })).not.toBeInTheDocument()
})
