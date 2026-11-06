# Shared commercial preview control plane

Status: isolated administrator preview, not production financial cutover.
Parent #408 / commercial epic #413; extends Draft PR #415.
User clarification: the offer document remains unchanged.

## Administrator surfaces and ownership

The same component is mounted behind the existing server-verified administrator
preview in Telegram and VK. No Telegram account is required for a permitted VK
administrator. Global catalog changes use one DB-backed setting,
`shared_accounts.commercial_preview`; no live price.json or VK pricing setting is
updated. Defaults are empty, so unconfigured prices fail closed instead of
silently becoming free. Administrator edits are versioned with compare-and-swap
and durable before/after audit. Audit failure rolls back the setting change.

Tariffs contain editable model/mode price positions with exact four-place banana
amounts and a job/second unit. Partner groups independently contain first/second
level percentages and repeat-reward rubles. Account assignments separately select
a tariff, partner group and optional individual rates/reward. Null means inherit;
explicit zero remains zero. A collaboration commission never implies a creator
price or administrative permission. Production rollout will bind catalog positions
to the existing validated generation quote inputs rather than trusting client
quantities or inventing a second generation-pricing authority.

Both clients can inspect a verified existing identity's account and edit its
preview assignment. The server obtains the acting identity from a revocable
session, then enforces the preview administrator ceiling. Client role, tariff,
account or platform fields cannot select another price in a self quote. Existing
legacy identities are not bulk imported, and no fake Telegram ID is created.

## Merge and concurrency

Lock order: link row, catalog row, sorted accounts. Assignment edits take catalog
then account; catalog edits hold the catalog lock while validating references.
A referenced tariff/group cannot be deleted underneath a current assignment.

One explicit assignment survives merging with an inherited/default assignment.
Conflicting nonempty assignments require administrator reconciliation and abort
the entire link transaction before money moves. No union of privileges or
maximum-rate heuristic is used. Every merge raises the canonical terms revision
to max(source revisions)+1, even when one assignment is explicitly empty. This
prevents a stale form addressed to an alias from erasing an individual agreement.

## Quote snapshots and payment boundary

A self quote uses the canonical launching account, its current saved assignment
and catalog, and its verified session platform. It persists an append-only preview
snapshot with revisions, total, unit/quantity, effective account terms and source
platform. Later policy edits never rewrite that snapshot. Old quote ownership
follows merged aliases; unrelated accounts cannot read it.

VK preview quotes allow only Lava. A linked Telegram identity cannot change a VK
session's origin, and client provider/platform overrides are rejected. Telegram
checkout methods remain with the existing payment adapter (the preview supplies
no new Telegram checkout). This slice creates neither provider invoices nor real
wallet debits. Real checkout/order creation and referral payout must use their
separate recipient/order snapshots and consume the platform constraint in the
future shared payment adapter. A launching account's displayed partner terms are
not a recipient commission calculation. Existing historical orders/webhooks and
merchant credentials are untouched.

## UI consistency and validation

Catalog saves refresh the selected account's saved effective terms from the
server while preserving any unsaved assignment and its original CAS revision.
If that refresh fails, the UI marks effective terms stale instead of showing an
old rate as current. Explicit reload refreshes the selected account. New quote
requests clear earlier displayed estimates. Money/percent inputs remain strings;
only quantities are parsed as bounded integers.

Coverage includes both DB engines, shared TG/VK administration, exact amounts,
individual 40% vs generic 30%, explicit zero, stale/conflicting edits, immutable
snapshots, audit rollback, merge conflicts and pre-merge alias CAS, verified VK
origin, permissions, cross-account quote access and inherited-rate UI refresh.
The browser smoke exercises editing a price, assigning creator/individual terms
and calculating the result in TG/VK while ordinary users remain excluded.

No production merge, deployment, schema migration, merchant registration or real
provider submission is part of this change. Live financial adapters, legacy
opening reconciliation and full VK generation/history/feed parity remain release
gates of the overall product.
