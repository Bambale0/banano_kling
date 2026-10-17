# Seedance reference binding incident — 2026-10-17

## Confirmed code defect

The canonicalizer previously converted an out-of-range `@ImageN` to `@VideoN` or `@AudioN` whenever those media happened to be present. This could silently change a paid prompt's meaning when an image was missing. The default now preserves typed image references so existing missing-reference validation fails before charging and provider submission. Explicit legacy conversion remains opt-in for a caller that can prove a combined-ordinal contract.

## Scope and limitations

This is a fail-closed guard, not a restoration of missing assets. Audit DB media mappings, storage lifecycle/cleanup, signed URL expiry, original works, repeat payloads and billing before declaring the incident resolved. Do not run destructive cleanup until live-reference reachability and backup checks have completed. Existing dirty production files must not be overwritten.

## Verification

Run `pytest -q tests/test_seedance_missing_reference_guard.py tests/test_seedance_trend_reference_recipes.py`, then targeted Seedance integration tests, CI, and a production smoke after deployment. Inspect task payload, validation response and balance to verify that a missing `@ImageN` never charges. No tests or deployment are claimed by this document.
