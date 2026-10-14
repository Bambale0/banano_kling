/**
 * Legacy clipboard write must run synchronously within the user's tap on iOS.
 * Telegram's iOS WKWebView can reject the async Clipboard API, and trying the
 * fallback only after awaiting that rejection loses transient user activation.
 */
function tryCopySelection(value: string, visibleField?: HTMLInputElement | null): boolean {
  if (typeof document.execCommand !== 'function') return false
  const useVisibleField = Boolean(visibleField?.isConnected && visibleField.value === value)
  const field = useVisibleField ? visibleField! : document.createElement('textarea')
  // WKWebView sometimes reports success only for a focused *editable* field.
  // Temporarily lift readOnly inside the same tap, then restore it.
  const oldReadOnly = field.readOnly
  if (useVisibleField) field.readOnly = false
  if (!useVisibleField) {
    const area = field as HTMLTextAreaElement
    area.value = value
    area.readOnly = false
    area.dataset.clipboardFallback = 'true'
    area.style.position = 'fixed'
    area.style.left = '0px'
    area.style.top = '0px'
    area.style.width = '1px'
    area.style.height = '1px'
    area.style.opacity = '0'
    area.style.pointerEvents = 'none'
    area.style.fontSize = '16px'
    document.body.appendChild(area)
  }
  try {
    field.focus({ preventScroll: true })
    field.select()
    field.setSelectionRange(0, value.length)
    return document.execCommand('copy') === true
  } catch {
    return false
  } finally {
    if (useVisibleField) field.readOnly = oldReadOnly
    else field.remove()
  }
}

export async function copyTextToClipboard(
  text: string,
  visibleField?: HTMLInputElement | null,
): Promise<void> {
  const value = String(text || '').trim()
  if (!value || typeof document === 'undefined') throw new Error('Ссылка пока недоступна')

  const platform = typeof window !== 'undefined' ? window.Telegram?.WebApp?.platform : undefined
  const isIOS = platform === 'ios'
    || (typeof navigator !== 'undefined' && /iPhone|iPad|iPod/i.test(navigator.userAgent))
  // A visible share input is also selected synchronously on Android; copying
  // still works when Telegram grants only a short-lived tap permission.
  // Prefer selecting the on-screen field while the browser still has the
  // user's tap activation. If Telegram disallows copying a visible input,
  // retry with a temporary editable textarea before awaiting a permission API.
  if (isIOS || visibleField) {
    if (tryCopySelection(value, visibleField)) return
    if (visibleField && tryCopySelection(value)) return
  }

  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return
    } catch {
      // Other Telegram WebViews may deny clipboard permissions.
    }
  }

  if (!isIOS && !visibleField && tryCopySelection(value)) return
  throw new Error('Не удалось скопировать ссылку')
}
