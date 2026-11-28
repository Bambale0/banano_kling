# Astro month facts and tariff editor

Baseline: 25af12d2525b5085e1d253435b5f6dc116d13e56 (tanyapi). Incident: month report failed with invalid_report_content before provider invocation; verified compact facts 157231 bytes (31 chronological samples), compared with a 150000 byte intermediate cap and 250000 byte encrypted job limit. Align intermediate cap with queue, compact provider JSON, retain separate provider request size guard and log only byte count if oversized.

Restore the seven-service admin tariff editor from unmerged PR #625, including CAS, shared publisher lock, validation and legacy tariff preservation. Address previous review finding: integer price must be editable to fractional price. Catalog only: no debits, public access, or invented prices. Reuse existing price.json, no migration.

Regression tests: 31-day report larger than previous intermediate limit with fake provider, all sections and unchanged facts; tariff editor existing suite plus integer-to-fractional price. Production investigation and date expansion verified; local pytest and real PDF delivery not yet verified. CI and normal release gates required. No manual restart or production mutation performed for this incident.
