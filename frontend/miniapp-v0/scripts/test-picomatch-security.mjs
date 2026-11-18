import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const target = process.env.PICOMATCH_SECURITY_TARGET
  || require.resolve('picomatch')
const matcher = require(target)

test('repeated extglob attacks cannot hold the matching thread', () => {
  for (const pattern of ['+(*)b', '+(*a)b', '*(*)b', '*(*a)b', '+(a|aa)b', '+(a?(a))b', '+(a)'.repeat(20) + 'b', '@(*)+b', '(a|aa)+b']) {
    for (const options of [{}, { maxExtglobRecursion: false }, { nocase: true }, { noext: true }, { noextglob: true }, { regex: true }]) {
      const child = spawnSync(process.execPath, ['-e',
        'const pm=require(process.argv[1]);const [p,o]=JSON.parse(process.argv[2]);'
        + 'try { for(const s of ["a".repeat(128)+"!", "+"+"a".repeat(128)+"!"])if(pm.makeRe(p,o).test(s)) process.exit(2); }'
        + 'catch(e) {if(!(e instanceof SyntaxError)||!e.message.startsWith("Repeated extglobs are disabled"))throw e;}',
        target, JSON.stringify([pattern, options])],
      { timeout: 1500, encoding: 'utf8' })
      assert.equal(child.error?.code, undefined, `matching exceeded budget: ${pattern}`)
      assert.equal(child.status, 0, `matcher failed: ${pattern}: ${child.stderr}`)
    }
  }
})

test('ordinary glob and configured Jest file-selection behavior stays usable', () => {
  const cases = [
    ['components/tabs/astro-report-panel.test.tsx', '**/?(*.)@(spec|test).?([mc])[jt]s?(x)', true],
    ['lib/sample.spec.js', '**/?(*.)@(spec|test).?([mc])[jt]s?(x)', true],
    ['lib/source.ts', '**/?(*.)@(spec|test).?([mc])[jt]s?(x)', false],
    ['src/a/b/file.ts', 'src/**/*.ts', true],
    ['src/.hidden.ts', 'src/**/*.ts', false],
    ['foo', '@(foo|bar)', true],
    ['quux', '@(foo|bar)', false],
    ['image.png', '*.{jpg,png}', true],
    ['file.test.ts', '*.!(js)', true],
  ]
  for (const [input, pattern, expected] of cases) assert.equal(matcher.isMatch(input, pattern), expected, pattern)
  assert.equal(matcher.scan('src/**/*.ts').isGlob, true)
  assert.throws(() => matcher.makeRe('a'.repeat(4097)), /length limit|exceeds maximum/)
})

test('unsupported repeats fail explicitly, including exclusions and parser entry points', () => {
  const posix = require(target.replace(/index\.js$/, 'posix.js'))
  for (const pm of [matcher, posix]) {
    for (const options of [{}, { maxExtglobRecursion: false }, { fastpaths: false }, { capture: true }, { bash: true }]) {
      for (const pattern of ['+(foo|bar)', '*(foo|bar)', '**/*.+(pem|key)', '!(+(a))']) {
        assert.throws(() => pm.makeRe(pattern, options), /Repeated extglobs are disabled/)
        assert.throws(() => pm.parse(pattern, options), /Repeated extglobs are disabled/)
      }
    }
  }
  assert.throws(() => matcher.makeRe('+(foo|bar)', { noext: true }), /Repeated extglobs are disabled/)
  assert.throws(() => matcher.makeRe('+(foo|bar)', { noextglob: true }), /Repeated extglobs are disabled/)
  assert.equal(matcher.makeRe('(a|aa)+b', { regex: true }).test('aaaaaab'), false)
})
