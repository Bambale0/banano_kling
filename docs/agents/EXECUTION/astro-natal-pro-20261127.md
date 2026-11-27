# Natal instruction — 2026-11-27

Baseline: 12f061440c04fe4d8679c49c8b7c1fd5157b4c3e (tanyapi). Scope: only natal report instructions and section plan. Owner source: docs/astro/natal-system-pro-20261127.md (SHA-256 3266f907aad9c2c096bcbf850c1bc15cc0a78ed101f406e09e1ba1414149d60c).

- Existing external JSON plan loader and global factual/JSON policy retained. Version v5; 19 topics, topic 14 expanded into 12 separate house sections (30 jobs total), existing minimum 11000 words. No changes to prices, provider, schemas, API, UI, payment or PDF pipeline.
- Archived v4 exactly; worker resolves existing HMAC-signed v4, v3 and v2 tasks. No data migration. Existing checkpoints stay scoped to the original fingerprint.
- Updated regression tests for exact source, complete topic coverage, all houses, isolation, signed old/new jobs and tamper rejection.
- Connector readback verified exact source, global policy, all six other service definitions, archive equality, section count and total minimum. Python pytest and production smoke not executed in this session; required CI gates must pass before merge. Production release and delivery are not verified.
- Rollback: revert task PR through normal tanyapi workflow; note already-created v5 jobs require retained v5 plan if rolling back after release.
