import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const root = fileURLToPath(new URL('../', import.meta.url))
const vendor = join(root, 'vendor/picomatch')
const json = path => JSON.parse(readFileSync(path, 'utf8'))
const provenance = json(join(vendor, 'PROVENANCE.json'))
const manifest = json(join(vendor, 'package.json'))
const require = createRequire(import.meta.url)
assert.equal(manifest.name, '@neuromix/picomatch-hardened')
assert.equal(manifest.version, '4.0.7+neuromix.1')
assert.equal(provenance.fixedAdvisory, 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf')
assert.equal(provenance.upstream.name, 'picomatch')
assert.equal(provenance.upstream.version, '4.0.7')

const lock = json(join(root, 'package-lock.json'))
const resolved = Object.entries(lock.packages).filter(([path]) => path.endsWith('/picomatch'))
assert.ok(resolved.length > 0, 'No resolved picomatch installation')
for (const [path, pkg] of resolved) {
  assert.equal(pkg.name, manifest.name, `Unpatched identity: ${path}`)
  assert.equal(pkg.version, manifest.version, `Unpatched version: ${path}`)
  assert.equal(pkg.resolved, 'file:vendor/picomatch', `Unpatched source: ${path}`)
  assert.equal(createRequire(join(root, path, 'package.json')).resolve(join(root, path)),
    join(root, path, 'index.js'), `Unreviewed installed entry point: ${path}`)
  for (const [file, hashes] of Object.entries(provenance.files)) {
    for (const base of [vendor, join(root, path)]) {
      const actual = createHash('sha256').update(readFileSync(join(base, file))).digest('hex')
      assert.equal(actual, hashes.patchedSha256, `Changed security-reviewed bytes: ${base}/${file}`)
    }
  }
}
assert.equal(require.resolve('picomatch'), join(root, 'node_modules/picomatch/index.js'))

const run = (args, cwd = root) => {
  const result = spawnSync(process.execPath, args, { cwd, encoding: 'utf8', timeout: 120_000 })
  assert.ifError(result.error)
  return result
}
const tests = run(['--test', 'scripts/test-picomatch-security.mjs'])
process.stdout.write(tests.stdout)
assert.equal(tests.status, 0, tests.stderr || 'Security regression failed')

// A private package identity is invisible to the registry's upstream advisory
// database. Audit the original version as well, never just the renamed fork.
const npm = process.env.npm_execpath
assert.ok(npm, 'Run through npm run security:picomatch')
const scratch = mkdtempSync(join(tmpdir(), 'neuromix-upstream-audit-'))
try {
  writeFileSync(join(scratch, 'package.json'), JSON.stringify({
    name: 'neuromix-upstream-advisory-check', version: '1.0.0', private: true,
    dependencies: { picomatch: provenance.upstream.version },
  }))
  const install = run([npm, 'install', '--package-lock-only', '--ignore-scripts', '--no-audit', '--fund=false'], scratch)
  assert.equal(install.status, 0, 'Unable to resolve original upstream advisory baseline')
  const upstream = json(join(scratch, 'package-lock.json')).packages['node_modules/picomatch']
  assert.equal(upstream.version, provenance.upstream.version)
  assert.equal(upstream.integrity, provenance.upstream.integrity, 'Official upstream integrity changed')
  const audit = run([npm, 'audit', '--json'], scratch)
  assert.ok(audit.status === 0 || audit.status === 1, 'Upstream advisory query failed')
  const report = JSON.parse(audit.stdout)
  assert.ok(!report.error && report.metadata && report.vulnerabilities, 'Incomplete upstream audit response')
  for (const [name, finding] of Object.entries(report.vulnerabilities)) {
    assert.equal(name, 'picomatch', `Unexpected upstream dependency advisory: ${name}`)
    for (const advisory of finding.via) {
      assert.equal(typeof advisory, 'object', 'Unexpected transitive advisory')
      assert.equal(advisory.url, provenance.fixedAdvisory,
        `New upstream advisory needs review: ${advisory.url}`)
    }
  }
  console.log('Pinned private fix verified; original upstream advisory remains visible. Other advisories: none.')
} finally {
  rmSync(scratch, { recursive: true, force: true })
}
