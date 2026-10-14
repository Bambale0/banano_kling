# Oversized Telegram delivery reconciliation

Baseline: a1b1ce4ae6f8c6b52cea06c7527fa61c645339c5. Dedicated branch fix/tanya-oversize-delivery-20261014.

## Diagnosis and scope
A completed Motion result with a confirmed fallback link remained pending. The normal KIE webhook writes link_sent followed by pending, and watchdog selects both. Uploaded-file Telegram size rejection was not persisted separately, so each replay repeated the impossible upload.

## Invariants
- Provider completion, result URL/history, download action and charge remain unchanged.
- Only a typed Telegram rejection of the uploaded file establishes durable oversize evidence. URL-size errors alone retain the file fallback.
- link_delivered is a terminal link receipt, never a Telegram video receipt.
- Oversize marker preserves the active delivery lease. Failed link delivery releases pending; the next attempt sends only the link.
- Confirmed prior link plus newly proven oversize finalizes without resending the link.
- Delivery metadata updates use JSON compare-and-swap and reread to avoid terminal downgrade by stale writers.
- No historical SQL patch, manual resend/refund, deletion or transcode is performed.

## Verification
Initial actual persistence regression: 2 failures and 1 error on baseline; green after the fix. Actual KIE delivery block is exercised with fake Telegram and download transports, no application imports. Cases cover size rejection, successful/failed link, restart, prior link, URL-size fallback success and transient download failure. Shared persistence tests cover terminal outcome, lease, duplicate completion and watchdog SQL.
Official full application/database suite, CI and independent final review remain required. Production has not been changed.

## Rollout
Draft PR to tanyapi, exact-head CI and review, pre-release report, guarded release. Existing affected tasks gain evidence through normal reconciliation, not a manual historical mutation; one fresh file rejection may occur before their old link receipt finalizes. Observe bounded post-release metadata for task309699 without sending or downloading user media.

## Guidance
AGENTS, local Bambale0/skills TDD, Claw workflow and Anthropic testing guidance consulted. Previously denied playbook refresh was not repeated. Frontend is unchanged; no schema migration or price configuration changes.
