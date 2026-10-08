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
 await screen.findByText(/Автоматическое копирование недоступно/)
 expect(scrollRecovery).toHaveBeenCalledWith({ block: 'center' })
 writeText.mockResolvedValueOnce(undefined)
 const previous = writeText.mock.calls.length
 fireEvent.click(screen.getByRole('button', { name: 'Скопировать ссылку' }))
 // Clipboard is invoked synchronously in this fresh event, before any await.
 expect(writeText.mock.calls.length).toBe(previous + 1)
 expect(await screen.findByText('Ссылка скопирована')).toBeInTheDocument()
 expect(screen.queryByText(/Автоматическое копирование недоступно/)).not.toBeInTheDocument()
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
