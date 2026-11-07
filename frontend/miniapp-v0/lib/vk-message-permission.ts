type NativeWindow = Window & {
  AndroidBridge?: Record<string, (data: string) => void>
  webkit?: { messageHandlers?: Record<string, { postMessage?: (data: { group_id: number }) => void }> }
  ReactNativeWebView?: { postMessage?: (data: string) => void }
}

// Same native transport used by the entry handshake. This opens VK's consent
// dialog only; the server still checks the actual permission before sending.
export function requestVkMessagePermission(communityId: number): boolean {
  if (typeof window === 'undefined' || !Number.isSafeInteger(communityId) || communityId <= 0) return false
  const host = window as NativeWindow
  const handler = 'VKWebAppAllowMessagesFromGroup'
  const params = { group_id: communityId }
  try {
    if (typeof host.AndroidBridge?.[handler] === 'function') {
      host.AndroidBridge[handler](JSON.stringify(params))
    } else if (typeof host.webkit?.messageHandlers?.[handler]?.postMessage === 'function') {
      host.webkit.messageHandlers[handler].postMessage?.(params)
    } else if (typeof host.ReactNativeWebView?.postMessage === 'function') {
      host.ReactNativeWebView.postMessage(JSON.stringify({ handler, params }))
    } else if (window.parent !== window && typeof window.parent.postMessage === 'function') {
      // Only a public community ID is passed, never a token or session.
      window.parent.postMessage({ handler, params, type: 'vk-connect', connectVersion: '3.0.2' }, '*')
    } else return false
    return true
  } catch { return false }
}
