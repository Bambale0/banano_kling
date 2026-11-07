import { requestVkMessagePermission } from '../vk-message-permission'

afterEach(() => {
  for (const key of ['AndroidBridge', 'webkit', 'ReactNativeWebView']) {
    Object.defineProperty(window, key, { configurable: true, writable: true, value: undefined })
  }
})

test('Android permission request contains only the server community ID', () => {
  const send = jest.fn()
  Object.defineProperty(window, 'AndroidBridge', { configurable: true, value: { VKWebAppAllowMessagesFromGroup: send } })
  expect(requestVkMessagePermission(456)).toBe(true)
  expect(send).toHaveBeenCalledWith(JSON.stringify({ group_id: 456 }))
})

test('iOS permission request uses the native method without claiming consent', () => {
  const send = jest.fn()
  Object.defineProperty(window, 'webkit', { configurable: true, value: { messageHandlers: { VKWebAppAllowMessagesFromGroup: { postMessage: send } } } })
  expect(requestVkMessagePermission(456)).toBe(true)
  expect(send).toHaveBeenCalledWith({ group_id: 456 })
})

test('React Native request uses the established handler envelope', () => {
  const send = jest.fn()
  Object.defineProperty(window, 'ReactNativeWebView', { configurable: true, value: { postMessage: send } })
  expect(requestVkMessagePermission(456)).toBe(true)
  expect(JSON.parse(send.mock.calls[0][0])).toEqual({ handler: 'VKWebAppAllowMessagesFromGroup', params: { group_id: 456 } })
})

test('plain browser and invalid community do not pretend to open native consent', () => {
  expect(requestVkMessagePermission(456)).toBe(false)
  expect(requestVkMessagePermission(-1)).toBe(false)
})
