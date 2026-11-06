import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

const layoutSource = readFileSync(new URL('../app/layout.tsx', import.meta.url), 'utf8')

function compiledEarlyBootstrap(vkBuild) {
  const match = layoutSource.match(/const telegramBootstrapScript = `([\s\S]*?)`\n\nexport const metadata/)
  assert.ok(match, 'early bootstrap script must remain discoverable')
  return match[1].replace("${JSON.stringify(process.env.NEXT_PUBLIC_MINIAPP_PLATFORM === 'vk')}", JSON.stringify(vkBuild)).replace("${containsAccountLink.toString()}", 'function containsAccountLink() { return false }')
}

test('VK launch dismisses the native loader through VKWebAppInit before React hydration', () => {
  let nativeLoaderVisible = true
  const sent = []
  const parent = {
    postMessage(message, targetOrigin) {
      sent.push({ message, targetOrigin })
      if (message?.type === 'vk-connect' && message?.handler === 'VKWebAppInit') nativeLoaderVisible = false
    },
  }
  const storage = new Map()
  const window = {
    location: { hash: '', origin: 'https://vk.neuromixbot.com', search: '?vk_app_id=123&vk_user_id=2001&sign=browser-test' },
    parent,
    sessionStorage: {
      getItem: key => storage.get(key) ?? null,
      removeItem: key => storage.delete(key),
      setItem: (key, value) => storage.set(key, String(value)),
    },
    addEventListener() {},
    setTimeout() {},
  }
  vm.runInNewContext(compiledEarlyBootstrap(true), { URLSearchParams, window })
  assert.equal(nativeLoaderVisible, false, 'VK native loader remains visible without VKWebAppInit')
  assert.equal(sent.filter(({ message }) => message?.handler === 'VKWebAppInit').length, 1)
})

test('VK launch initializes Android and iOS native clients without posting to the web parent', () => {
  for (const platform of ['android', 'ios']) {
    const nativeCalls = []
    const parentCalls = []
    const window = {
      location: { hash: '', origin: 'https://vk.neuromixbot.com', search: '?vk_app_id=123&vk_user_id=2001' },
      parent: { postMessage: message => parentCalls.push(message) },
      sessionStorage: { removeItem() {} },
      addEventListener() {},
      setTimeout() {},
    }
    if (platform === 'android') {
      window.AndroidBridge = { VKWebAppInit: payload => nativeCalls.push(JSON.parse(payload)) }
    } else {
      window.webkit = { messageHandlers: { VKWebAppInit: { postMessage: payload => nativeCalls.push(payload) } } }
    }

    vm.runInNewContext(compiledEarlyBootstrap(true), { URLSearchParams, window })

    assert.equal(JSON.stringify(nativeCalls), '[{}]', platform)
    assert.deepEqual(parentCalls, [], platform)
  }
})

test('Telegram launch keeps its existing ready handshake and does not initialize VK', () => {
  const sent = []
  const window = {
    location: { hash: '', origin: 'https://neuromixbot.com', search: '' },
    parent: { postMessage: message => sent.push(message) },
    sessionStorage: { setItem() {}, removeItem() {} },
    addEventListener() {},
    setTimeout() {},
  }

  vm.runInNewContext(compiledEarlyBootstrap(false), { URLSearchParams, window })

  assert.equal(sent.some(message => message?.handler === 'VKWebAppInit'), false)
  assert.equal(sent.some(message => {
    if (typeof message !== 'string') return false
    return JSON.parse(message).eventType === 'web_app_ready'
  }), true)
})

