/** Observability for VK WebView launch, without sending signed URL params or IDs. */
export function reportVkLaunchStage(event: 'vk-react-mounted' | 'vk-session-start' | 'vk-session-ok' | 'vk-session-failed'): void {
  if (typeof window === 'undefined') return
  try {
    const body = JSON.stringify({ event, href: window.location.pathname || '/' })
    const endpoint = '/mini-app/api/client-log'
    if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
      if (navigator.sendBeacon(endpoint, new Blob([body], { type: 'application/json' }))) return
    }
    void fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {})
  } catch {
    // Telemetry must never break launch or reveal credentials in fallback logs.
  }
}
