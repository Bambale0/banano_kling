# VK delivery reconciliation — bounded scan hotfix (2026-11-13)

Production diagnosis: every five seconds the VK delivery worker queried
all historical `generation_tasks` (~378,000 rows / 2.1 GB), applying JSON
predicates and joining deliveries before `LIMIT 50`. The query was seen
running over 16 seconds and contending with Telegram/Mini App traffic.

`VKDeliveryQueue.reconcile()` now reads a bounded ordered raw-ID window,
evaluates the unchanged eligibility contract only within the window and
moves its in-memory cursor past ineligible rows. A partial final window
wraps to zero for eventual reconsideration, including formerly ineligible
results. Direct notification enqueue, recipient/auth policy, and idempotent
delivery records remain unchanged.

`VK_RESULT_RECONCILE_SCAN_BATCH` controls the technical batch size;
default 500, clamped to 1..5000. Lower values reduce each sweep's load
while increasing time to complete a full historical pass. The worker
still runs every five seconds. The cursor is ephemeral: after a process
restart the scan begins at the oldest ID, which remains safe.

TDD: regression test first failed on the old method and then passed;
33 VK/Kling integration tests passed locally (26 environment skips).
Ruff and git diff check passed. Production read-only EXPLAIN for a 500
row batch selects an index scan on generation_tasks_pkey (LIMIT cost ~469).

Release verification: exact SHA CI and deploy, then measure Telegram event
p50/p95, Mini App bootstrap p50/p95, database pool exhaustions and VK
notification delivery with the existing production telemetry.
