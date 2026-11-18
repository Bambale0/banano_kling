# Mini App dependency security remediation — 2026-11-18

Baseline `tanyapi`: `2d454199a2677e3446d4d4b35b35fe2a0ce1add0` (PDF delivery #600).

## Preflight and intended result

- #599 is blocked by the existing high-severity npm audit gate: GHSA-fc5q-39xc-vjpf / CVE-2026-112366. Official registry latest is picomatch 4.0.7 and the advisory lists no patched release. Do not suppress the advisory, weaken audit scope/severity, fake an upstream version or remove required CI.
- Continue toward the user's explicit 100% readiness requirement through a separate security PR. UI copy, PDF delivery and section rewrites remain separate PRs.
- Evaluate a private, vendored MIT-licensed fork of exact upstream 4.0.7. Reject all active repeated extglobs explicitly; ordinary glob/Jest matching must retain tested behavior. Preserve upstream license and verified registry integrity, record exact patch/file hashes and local fork identity explicitly.
- A clean audit of a renamed fork alone is insufficient. Keep the existing audit unchanged and add a gate that checks the original upstream version for new advisories, accepts the known advisory as fixed only when pinned patched bytes and independent bounded-execution regressions verify it, and fails for unknown upstream advisories.

## Steps and acceptance

1. Verify official tarball integrity; retain provenance/license; demonstrate the original vulnerability in a disposable subprocess.
2. Add the minimal guard and public-interface timeout/functional regressions, including opt-out bypass attempts and actual Jest file-selection patterns.
3. Use explicit file overrides to the private fork without pretending it is an upstream patched release. Verify every resolved picomatch installation is the pinned patched source.
4. Add the provenance/upstream-advisory regression gate alongside unchanged npm audit; record unmodified upstream baseline advisories transparently.
5. Review security and compatibility; run all applicable Mini App tests, type/lint/build/browser and protected CI. Do not publish a speculative patch or claim 100% based solely on audit output.
6. Only after validation, native squash auto-merge into protected `tanyapi`, exact-SHA production CI/autodeploy and smoke. Rollback is the previous lockfile/vendor state; do not remove the audit gate.

## Implementation and evidence

- Verified official 4.0.7 tarball SHA512 against registry integrity; original MIT license and per-file upstream SHA256 retained. Private identity is `@neuromix/picomatch-hardened@4.0.7+neuromix.1`, never an invented official patched version. npm file override and `install-links=true` resolve all consumers to this source; lockfile changes otherwise only recalculate optional dependency flags.
- Original `+(*)b` timed out in a disposable 1500ms subprocess (RED). Independent review also disproved an initial local-body guard with adjacent `+(a)` groups; that candidate was rejected. Final policy rejects `+(`/`*(` before aliases/fast paths, including escaped occurrences and noext/noextglob. Forces parser regex:false even for regex:true requests to prevent raw-plus fallback. The obsolete upstream analyzer is removed. Length is capped at 4096 before fast paths. This is a dev/build-only dependency for repository-owned patterns; ordinary complex glob composition can still backtrack. No untrusted-pattern or general regex-safety claim.
- Installed public entry, posix entry, parse, options and exclusion behavior tested. Gate pins source/installed bytes including manifest, verifies actual entry-point resolution, runs bounded regressions and queries original upstream advisories. Unknown advisories/network errors fail closed. Existing `npm audit --audit-level=high` is unchanged and exits 0; 19 inherited moderate findings remain visible (glob/minimatch/Next), not suppressed.
- Configured Jest finite alternation instead of unbounded repeated selector. Actual baseline/current Jest discovery inventories are identical: 122 files. Local installation completed; focused security gate has 3 passing tests. Final source bytes were synchronized to that development installation after review fixes; Linux/CI must additionally verify a clean locked install.
- Full frontend regression initially exposed one baseline-stale lazy-preview assertion (975 passed, one failed). Isolated #602 corrected that expectation and merged as `18829b14fa9cd76d31f3dff801fa90ea7b1f3060`; this branch is synced to that production target. Combined source was independently verified on Linux: all 122 suites / 976 tests pass.
- Clean Node 22.23.0/npm 12.0.2 Linux locked installation, security gate, unchanged high-severity audit, TypeScript, lint and production build pass. Negative public-gate probes confirm rejection of a new advisory, failed advisory query, changed entry-point manifest and changed implementation bytes. Protected CI must rerun on the final synced head.
- Independent standards/spec review and protected CI remain release requirements. No production modification is performed by this dependency gate; no credentials, customer data, provider calls or payments are involved.

## Browser prerequisite repair

Two exact-head CI runs (production target `18829b14` and candidate `4f9c89e9`) reached the existing 10-minute browser-install timeout while apt downloaded from `us-east-2.ec2.archive.ubuntu.com`. Logs and helper inspection proved the selected mirror was not applied: the rewrite matched only the unqualified/Azure archive host, leaving regional Ubuntu-owned source URIs untouched.

Extend that one rewrite to official archive.ubuntu.com subdomains. A new DEB822 regional-source fixture observed RED (original URL remained) then GREEN with the fix; the existing fallback/all-mirrors-unreachable tests and shell syntax checks pass. Signed-By is explicitly preserved, and actual signed apt update/install and all browser tests remain mandatory. No TLS/GPG bypass, timeout relaxation or skipped check. This is necessary preparation for the security PR's browser gate, not an Astro runtime change. Superseded head checks do not substitute for fresh final-head CI.
