# TG/VK commercial requirements — 06.11.2026

Status: required addition to #408 / #413, implementation pending. No deployment.

## Prices and entitlements

Use one authoritative administrator-managed price catalog for both platforms,
with model/mode and launching-account tariff as inputs. Existing prices remain
untouched until the administrator configures the intended shared values. Equal
inputs and tariff must quote the same amount in Telegram and VK.

Price tariff, collaboration membership and partner commission terms are separate
axes. Support ordinary users, creators and collaborating creators/partners without
conflating generation discounts with higher earnings. An ordinary visitor never
inherits the source author's tariff by repeating a publication.

Administrator surfaces in TG/VK operate on the same backend controls, with
server authorization, validation, revisions/CAS and before/after audit. No second
independent writable VK price or commission authority after cutover.

## Partner terms

Retain verified individual agreements across linked identities. An existing 40%
agreement must not fall back to the generic VK 30% rate. These are examples from
the request, not new universal constants. Do not grant 40% or creator privileges
to everybody; conflicting individual agreements require explicit reconciliation.
Unlinked VK-only accounts can receive memberships and terms through the admin UI.

Keep referral payment commissions, per-repeat rewards, banana spending and
accumulated partner rubles distinct. Accepted quote/order/reward snapshots retain
their policy version. New administrator values affect future operations only.

Observed source seams: VK load_runtime_settings uses shared prices/referral
settings and its payment commission paths use Config.REF_LEVEL_1_PERCENT.
TG partner_policy/effective_first_level_percent supports individual terms and
creator_tariff modules already separate generation prices. Adapt those seams to
account identity rather than duplicating business rules in VK. No live user terms
were queried and no production prices or percentages were changed in this audit.

## VK payments

Only the existing Lava connection is used for new VK purchases. No new merchant
registrations or provider integrations. Backend checkout selection is constrained
by the verified session origin, not a client platform/provider field. A linked
Telegram identity cannot enable Telegram payment methods inside a VK session.
Historical orders and webhook reconciliation continue under their original order
snapshot; hiding a checkout option must not lose a previously accepted payment.

## Pending clarification

The transcript phrase 'public offer' is ambiguous with a public feed of works.
Ask whether it means the offer document or public feed before changing either.
Do not hide documents, disable the feed, or change model visibility by guessing.

## Acceptance additions

- Ordinary, creator and collaborating creator quotes/earnings on both platforms.
- A verified individual 40% agreement survives a generic 30% fallback and merge.
- Equal generation inputs/tariff produce equal quotes in TG and VK.
- Source author entitlement never becomes a visitor entitlement through repeat.
- VK-only membership and individual terms can be managed by an authorized admin.
- VK shows only Lava; direct API cannot select other providers or forge origin.
- Existing pending orders and duplicate/late webhooks complete exactly once.
- Policy edits do not rewrite accepted order/quote/reward snapshots or history.
- Ordinary users cannot edit prices, commissions, memberships or personal terms.

Production merge/deployment, real data migration and public enablement remain on
hold until the complete shared product is finished. This document is a requirement
update, not a claim that the financial adapters are implemented.
