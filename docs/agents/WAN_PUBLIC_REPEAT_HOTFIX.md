# WAN public repeat hotfix

Base: 299422e5170a475fae9db045e6c34b8e32fc22ef. Addresses PR301 post-release review findings.

## Scope
- Public DTO preserves only a validated version-1 WAN routing marker. Private model, prompt, recipe, source ID and input media URLs remain hidden.
- Shared prompt deep links and ordinary-user cards open the protected WAN repeat plan, with no generic fallback on missing plans.
- Failed/retryable media uploads block every emitted publication draft until resolved or explicitly discarded.
- WAN metadata uses 60/200 character limits. WAN settings use a shared compact UTF-8 JSON budget of 64,000 bytes; generic settings retain their original limit. Instructions are never truncated.
- Unexpected WAN publication errors return a correlation ID. Protected diagnostics contain actor/model and bounded code-frame metadata, never exception text, source lines, locals, prompts or media.

## Verification before commit
- Actual sanitizer/privacy middleware isolated tests: 4 passed.
- Actual WAN publication boundary isolated tests: 4 passed, including exact 64,000/64,001 byte boundary and 20,000 Cyrillic characters.
- Full local frontend Jest with WAN_SUBMIT_FIXTURE=1: 60 suites / 465 tests passed.
- Full frontend TypeScript noEmit: passed.
- Scoped Ruff and diff whitespace checks: passed.
- Independent source and isolated review: no blockers on these changes.
- Official application/PostgreSQL/browser/build CI remains required on the final commit.

## Limits
No paid generation, production DB mutation, historical trend reactivation or customer-media access was performed. A separate mobile chunk parsing investigation remains open; these routing changes alone do not prove that real iPhone upload succeeds. The restricted generic API file was not locally read; serialization tests use the previously approved extracted fixture. The forbidden database adapter is excluded from this worktree and local application imports.

## Supplemental bounded chunk compatibility
The WAN JSON chunk reader now reuses aiohttp cached request bytes when present, instead of reading an exhausted stream. Actual raw-body, base64 and decoded 7 MiB caps remain enforced. Metadata-only accepted/rejected diagnostics help distinguish transport, cached/read lengths and exception class without logging content or auth.

Eleven standalone actual-route tests passed after integration (cached/stream parity, exact limits and false/missing content length, malformed JSON/UTF-8/base64, duplicate keys, unauthorized requests, metadata privacy). Scoped Ruff passed. An independent reviewer repeated all eleven tests and found no blocker.

This is defensive compatibility, not proof of the live incident's root cause. The actual production prereader remains unconfirmed. Real iPhone init/chunk/complete acceptance is still required after deployment; no generation is needed for that check.
