import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const configUrl = new URL('../next.config.mjs', import.meta.url).href
const patchScript = fileURLToPath(new URL('./patch-telegram-head.mjs', import.meta.url))

function buildConfig(basePath) {
  const env = { ...process.env, NEXT_EXPORT: '1' }
  delete env.NEXT_PUBLIC_MINIAPP_BASE_PATH
  if (basePath !== undefined) env.NEXT_PUBLIC_MINIAPP_BASE_PATH = basePath
  return JSON.parse(execFileSync(process.execPath, ['--input-type=module', '-e',
    `import config from ${JSON.stringify(configUrl)}; console.log(JSON.stringify(config))`], { env, encoding: 'utf8' }))
}

test('VK exports at domain root while the Telegram default retains /mini-app', () => {
  assert.equal(buildConfig('/').basePath, '')
  assert.equal(buildConfig('').assetPrefix, '')
  assert.equal(buildConfig().basePath, '/mini-app')
  assert.equal(buildConfig('/custom').basePath, '/custom')
})

test('root VK export versions root assets, inlines CSS and omits Telegram SDK', () => {
  const dir = mkdtempSync(join(tmpdir(), 'vk-export-'))
  try {
    mkdirSync(join(dir, 'out/_next/static/css'), { recursive: true })
    mkdirSync(join(dir, 'public'))
    writeFileSync(join(dir, 'public/telegram-web-app.js'), '// test SDK')
    writeFileSync(join(dir, 'out/_next/static/css/main.css'), 'body{color:red}')
    writeFileSync(join(dir, 'out/index.html'), '<html><head><meta charset="utf-8"><link rel="stylesheet" href="/_next/static/css/main.css"><script src="/_next/static/chunks/main.js"></script><script defer src="/mini-app/telegram-web-app.js"></script><script id="telegram-early-ready">window.launchCaptured=true</script></head><body></body></html>')
    execFileSync(process.execPath, [patchScript], { cwd: dir, env: { ...process.env,
      NEXT_PUBLIC_MINIAPP_BASE_PATH: '/', NEXT_PUBLIC_MINIAPP_PLATFORM: 'vk',
      MINIAPP_INLINE_CSS: '1', MINIAPP_ASSET_VERSION: 'test-version',
    } })
    const html = readFileSync(join(dir, 'out/index.html'), 'utf8')
    assert.match(html, /\/_next\/static\/chunks\/main\.js\?v=test-version/)
    assert.match(html, /<style[^>]*>body\{color:red\}<\/style>/)
    assert.match(html, /window.launchCaptured=true/)
    assert.doesNotMatch(html, /src="[^"]*telegram-web-app\.js/)
  } finally { rmSync(dir, { recursive: true, force: true }) }
})


test('Telegram export still injects its local SDK and versions prefixed resources', () => {
  const dir = mkdtempSync(join(tmpdir(), 'tg-export-'))
  try {
    mkdirSync(join(dir, 'out'), { recursive: true })
    mkdirSync(join(dir, 'public'))
    writeFileSync(join(dir, 'public/telegram-web-app.js'), '// test SDK')
    writeFileSync(join(dir, 'out/index.html'), '<html><head><meta charset="utf-8"><script src="/mini-app/_next/static/chunks/main.js"></script><script id="telegram-early-ready">window.launchCaptured=true</script></head><body></body></html>')
    const env = { ...process.env, MINIAPP_ASSET_VERSION: 'tg-version' }
    delete env.NEXT_PUBLIC_MINIAPP_BASE_PATH
    delete env.NEXT_PUBLIC_MINIAPP_PLATFORM
    execFileSync(process.execPath, [patchScript], { cwd: dir, env })
    const html = readFileSync(join(dir, 'out/index.html'), 'utf8')
    assert.ok(html.includes('src="/mini-app/telegram-web-app.js"'))
    assert.ok(html.includes('src="/mini-app/_next/static/chunks/main.js?v=tg-version"'))
    assert.ok(html.includes('window.launchCaptured=true'))
  } finally { rmSync(dir, { recursive: true, force: true }) }
})
