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
- Full frontend regression: 975 passed, one failed out of 976; the sole failure independently reproduced on baseline (stale lazy-preview assertion expecting an original video in the grid). A separate lazy-preview test-only follow-up corrects the intended deferred behavior; sync it after merge before final full regression. Security candidate did not introduce this failure. Type/lint and clean Linux/CI build remain required.
- Independent standards/spec review and protected CI remain release requirements. No production modification is performed by this dependency gate; no credentials, customer data, provider calls or payments are involved.
