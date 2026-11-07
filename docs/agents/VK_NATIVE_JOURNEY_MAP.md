# Independent VK entry, references and result delivery

Baseline: `tanyapi@00b40366c40b4684e23d8dfde0c3fc2c188bfbfb`.
Task branch: `feature/tanyapi-vk-native-journey`.

## Destination

A person arriving from VK can use the common NEUROMIX application without
creating a Telegram account. Linking is an explicit optional action. Selected
photos reach the provider and remain visible in the owner's source metadata.
Results stay available in the application and are delivered through the launch
platform when that platform's messaging permission exists.

## Notes

The user requests implementation, so this map carries execution through tested
slices rather than ending at planning. Integer screenshots are examples only.
Use diagnosing-bugs, test-first vertical slices and independent code review.
Do not manufacture Telegram IDs for VK users, silently merge identities or
move/normalize real balances. Do not send test messages to real users or submit
paid generations. Public rollout needs a complete verified native journey.

## Current evidence and reuse

- Shared identities, signed VK launches, revocable sessions and explicit link
  consent exist. The shared app currently rejects unlinked VK identities and
  requires a legacy Telegram user. The current policy is administrator-only.
- Generation APIs resolve that legacy actor, but do not persist launch platform.
  Existing direct and webhook result delivery addresses Telegram chats.
- Administrator task at 2026-11-07 08:33:38 UTC / 11:33:38 Moscow completed with
  zero provider/source reference URLs. It is the only administrator image task
  in the inspected 90-minute interval. No recent saved-reference rows were found
  for administrator users. This proves the missing provider input, not which
  client interaction caused it. No private prompt, media URL or credential is
  recorded here.
- Upload, saved library, task ownership, provider snapshots and delivery state
  already have public test seams. A category upload in the library's selection
  mode currently saves the file without selecting it for the surrounding form.
  Reproduce this concrete missing-reference path before changing it.
- Financial readiness ADRs explicitly identify legacy writer/precision barriers.
  Reuse existing live VK services only after identifying their actual contracts;
  sandbox shared-wallet code is not a live billing substitute.

## Decisions so far

- One frontend serves two independently usable platform entries. Telegram linking
  must not be a prerequisite for VK. Platform identity is server verified.
- Preserve reference selection and launch origin across asynchronous tasks; never
  infer launch channel from the existence of a linked Telegram identity.

## Research ticket: Existing native VK backend contracts

Question: Which authentication, actor, generation, storage, wallet and result
delivery contracts already exist in the active `Bambale0/tanyavk` repository,
and can the common app reuse them without invented Telegram identities or a
live balance migration? This is external-repository research; a read-only
research subagent owns it. No changes to that repository are authorized here.

Resolution: remote master `75159573c5f1b62263cae1e9bb46d5832a09ff20` and
running checkout `b06c6856072f1352d193d8987fe97e970d914ebf` have the same tree
`ec2b3439a3a08eeaaa41f6db2aa15aba88fc2f2e`. Native VK workers use real VK
user IDs, atomic task/debit creation, one-time refunds and VK result delivery.
They expose no browser session/upload/generate/history/wallet HTTP API. The
existing internal API exposes only GET health/stats; its HMAC contract does
not bind write bodies and cannot be reused unchanged for financial POSTs.

A native HTTP bridge alone would leave two writable wallets/histories after
linking, contrary to the existing shared-account requirements. An account-neutral
core needs one financial authority, account-owned inputs/tasks and persisted
verified origin/destination. Fresh VK read-only aggregates still show 214 balances
requiring precision review, one invalid negative balance and 6,107 stale shadow
unit values among 7,260 users. Shadow units are not a safe opening source.

## Decision ticket: Financial scope of the native VK release

An owner question is pending: retain the required common account/balance after
explicit linking (with prior legacy reconciliation), or explicitly stage a
standalone VK release with separate finances and defer unification. This affects
the actor/wallet migration contract, not merely UI copy. No choice, rounding,
negative-balance correction, live cutover or public policy activation is inferred
from silence. The independent reference-picker regression fix can ship while
this decision is pending.

## Implementation tickets

1. Reproduce library-upload-to-generation reference omission at the real form
   seam, then fix selection/error handling and verify the provider-bound URLs.
2. Resolve native VK actor/storage/payment seams from the research result; record
   the concrete design and migration/rollout implications before implementation.
3. Persist launch platform and verified delivery destination at task creation;
   route completion/retry through the corresponding adapter with idempotency.
4. Replace mandatory Telegram entry with native VK entry and optional profile
   linking, retaining server authorization and invalid/stale-launch recovery.
5. Verify new VK visitor, linked visitor, uploaded/saved reference and completion
   journeys on both platforms; protected PR, exact-SHA deploy and production smoke.

## Not yet specified

- Account-native actor bridge and compatibility with existing live VK balances.
- VK message permission, existing community token ownership and delivery API.
- Video/model-specific completion paths beyond the ordinary image seam.

## Verification and rollout

Each slice needs a symptom-specific RED/GREEN test. Applicable layers: identity
and permissions, Mini App API, actual form/browser, provider input, ownership,
DB compatibility, delivery retry/idempotency, billing invariants if touched,
deployment contracts and privacy-safe telemetry. No financial/config migration
is approved merely by this audit. Normal protected `tanyapi` PR/autodeploy is
required; production state is reported only after exact-SHA verification.

## Out of scope

Integer integration, unrelated text-bot features, provider/model rewrites,
unrelated cleanup and manual production deployments.
