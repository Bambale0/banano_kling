import '@testing-library/jest-dom'
import { startupRecoveryMarkup, startupRecoveryScript, STARTUP_RECOVERY_AFTER_MS } from '../startup-recovery'

const originalFetch = global.fetch
beforeEach(() => {
  jest.useFakeTimers()
  document.body.innerHTML = startupRecoveryMarkup
  global.fetch = jest.fn(async () => ({})) as unknown as typeof fetch
  window.eval(startupRecoveryScript)
})
afterEach(() => {
  window.__BANANO_BOOT_RECOVERY__?.done()
  delete window.__BANANO_BOOT_RECOVERY__
  document.body.innerHTML = ''
  global.fetch = originalFetch
  jest.useRealTimers()
})

test('startup watchdog shows native recovery without React and records no auth', () => {
  expect(document.getElementById('miniapp-startup-recovery')).not.toBeVisible()
  jest.advanceTimersByTime(STARTUP_RECOVERY_AFTER_MS)
  expect(document.getElementById('miniapp-startup-recovery')).toBeVisible()
  expect(fetch).toHaveBeenCalledTimes(1)
  const request = (fetch as jest.Mock).mock.calls[0]
  expect(request[0]).toBe('/mini-app/api/client-log')
  expect(JSON.parse(request[1].body)).toEqual({event: 'startup-assets-incomplete', phase: 'before-react', resource_path: ''})
})

test('mounted app disarms the watchdog so active drafts are never interrupted', () => {
  window.__BANANO_BOOT_RECOVERY__?.done()
  jest.advanceTimersByTime(60_000)
  expect(document.getElementById('miniapp-startup-recovery')).not.toBeVisible()
  expect(fetch).not.toHaveBeenCalled()
})

test('a delayed but successful mount hides the native fallback', () => {
  jest.advanceTimersByTime(STARTUP_RECOVERY_AFTER_MS)
  window.__BANANO_BOOT_RECOVERY__?.done()
  expect(document.getElementById('miniapp-startup-recovery')).not.toBeVisible()
  expect(jest.getTimerCount()).toBe(0)
})

test('fatal Next error replacing body cannot erase the recovery path', () => {
  document.body.innerHTML = '<h1>Framework error</h1>'
  jest.advanceTimersByTime(STARTUP_RECOVERY_AFTER_MS)
  expect(document.getElementById('miniapp-startup-retry')).toBeVisible()
})

test('resource telemetry excludes query parameters and external origins', () => {
  const script = document.createElement('script')
  script.src = '/mini-app/_next/static/chunks/test.js?v=build&token=not-for-logs'
  document.head.appendChild(script)
  script.dispatchEvent(new Event('error'))
  const external = document.createElement('script')
  external.src = 'https://unrelated.invalid/script.js?secret=never'
  document.head.appendChild(external)
  external.dispatchEvent(new Event('error'))
  jest.advanceTimersByTime(STARTUP_RECOVERY_AFTER_MS)
  const body = (fetch as jest.Mock).mock.calls[0][1].body
  expect(JSON.parse(body).resource_path).toBe('/mini-app/_next/static/chunks/test.js')
  expect(body).not.toMatch(/token|secret|not-for-logs|unrelated/)
  script.remove(); external.remove()
})
