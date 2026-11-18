# Lazy-preview regression alignment — 2026-11-18

Baseline `tanyapi`: `6d75db5ea847eeba0067186b51ccf6ea71e3ef1a`.

The #598 lazy-loading implementation is already deployed. Full frontend regression independently exposed one stale assertion on both baseline and security candidate: an extensionless signed original video was expected to exist in the grid before opening. Current intended behavior defers that original until explicit opening, preserving catalog media-kind detection.

Update only this regression: assert no video/image fetch element in the tile, then opening renders a controlled video with the signed URL. Keep this test follow-up separate from PDF #600, UI #599, quality #601 and dependency remediation. No runtime, configuration, schema, auth, payment or provider behavior changes.

Verification: baseline RED reproduced (16 pass, 1 failed in this file). Updated focused test and full frontend regression/CI are required before protected native squash release to `tanyapi`. Exact-SHA CI/autodeploy and origin health/revision verification remain required even for this test-only release. No S3 backfill repeated; the existing 91/91 remains untouched.
