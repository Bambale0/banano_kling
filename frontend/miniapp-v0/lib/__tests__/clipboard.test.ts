import { copyTextToClipboard } from '@/lib/clipboard'

const link = 'https://t.me/fixture_bot?startapp=remix_314699_ref_EXACT%2Bcode'

const nativeCopy = jest.fn()
const legacyCopy = jest.fn()

beforeEach(() => {
  jest.resetAllMocks()
  Object.defineProperty(navigator, 'userAgent', { configurable: true, value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)' })
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: nativeCopy } })
  Object.defineProperty(document, 'execCommand', { configurable: true, value: legacyCopy })
  nativeCopy.mockRejectedValue(new DOMException('Not allowed by Telegram', 'NotAllowedError'))
  legacyCopy.mockReturnValue(true)
})

it('copies synchronously on iOS Telegram before awaiting a denied Clipboard API promise', async () => {
  const events: string[] = []
  nativeCopy.mockImplementation(async () => { events.push('async-denied'); throw new DOMException('Denied', 'NotAllowedError') })
  legacyCopy.mockImplementation(() => {
    events.push('legacy')
    const selected = document.activeElement as HTMLTextAreaElement
    expect(selected.tagName).toBe('TEXTAREA')
    expect(selected.value).toBe(link)
    expect(selected.selectionStart).toBe(0)
    expect(selected.selectionEnd).toBe(link.length)
    expect(selected.style.position).toBe('fixed')
    expect(selected.style.left).toBe('0px') // not the -9999px field that iOS WebKit rejects
    return true
  })
  const copying = copyTextToClipboard(link)
  expect(events).toEqual(['legacy']) // before the first async turn or permission prompt
  await expect(copying).resolves.toBeUndefined()
  expect(nativeCopy).not.toHaveBeenCalled()
  expect(document.querySelector('textarea[data-clipboard-fallback]')).toBeNull()
})

it('copies the visible selected link on iOS in the original click without a hidden textarea', async () => {
  const field = document.createElement('input')
  field.value = link
  field.readOnly = true
  document.body.appendChild(field)
  legacyCopy.mockImplementation(() => {
    expect(document.activeElement).toBe(field)
    expect(field.selectionStart).toBe(0)
    expect(field.selectionEnd).toBe(link.length)
    return true
  })
  await expect(copyTextToClipboard(link, field)).resolves.toBeUndefined()
  expect(legacyCopy).toHaveBeenCalledWith('copy')
  expect(nativeCopy).not.toHaveBeenCalled()
  field.remove()
})

it('does not falsely report a copy when both clipboard APIs deny access', async () => {
  legacyCopy.mockReturnValue(false)
  await expect(copyTextToClipboard(link)).rejects.toThrow('Не удалось скопировать ссылку')
  expect(nativeCopy).toHaveBeenCalledWith(link)
})

it('does not attempt clipboard writes for an empty link', async () => {
  await expect(copyTextToClipboard('')).rejects.toThrow('Ссылка пока недоступна')
  expect(legacyCopy).not.toHaveBeenCalled()
  expect(nativeCopy).not.toHaveBeenCalled()
})
