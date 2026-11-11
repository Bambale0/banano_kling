import { reportVkLaunchStage } from '../vk-launch-telemetry'

const sendBeacon = jest.fn((_path: string, _blob: Blob) => true)
beforeEach(() => {
  window.history.replaceState({}, '', '/?vk_app_id=54880352&vk_user_id=2001&sign=' + 'a'.repeat(43))
  Object.defineProperty(navigator, 'sendBeacon', { value: sendBeacon, configurable: true })
})
afterEach(() => {
  sendBeacon.mockClear()
  Reflect.deleteProperty(navigator, 'sendBeacon')
  window.history.replaceState({}, '', '/')
})

test('client telemetry has no signed VK query, user identity, hash, or session credentials', async () => {
  reportVkLaunchStage('vk-react-mounted')
  expect(sendBeacon).toHaveBeenCalledTimes(1)
  const [path, blob] = sendBeacon.mock.calls[0]
  expect(path).toBe('/mini-app/api/client-log')
  const body = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(blob)
  })
  expect(JSON.parse(body)).toEqual({ event: 'vk-react-mounted', href: '/' })
})
