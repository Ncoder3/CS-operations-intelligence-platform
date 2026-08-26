# ADR 003 — Reporting Views Layer for Power BI

**Date:** 2026-08-26
**Status:** Accepted

## Context
Power BI could connect directly to the raw tables (`accounts`,
`support_tickets`, etc.) and do all the joining/filtering in Power Query or
DAX. That's the more common shortcut, but it means SLA-breach logic,
"latest survey per account," and CSM rollups would be defined twice — once
in Python (`src/scoring/`) and once in DAX — with no guarantee they agree.

## Decision
Created `sql/reporting_views.sql`: six SQL views (`vw_account_health`,
`vw_ticket_sla`, `vw_usage_trend`, `vw_latest_survey`, `vw_csm_performance`,
`vw_action_center`) that Power BI connects to directly instead of raw
tables. Business logic (SLA breach definition, latest-record-per-account,
CSM aggregation) lives here, in one place, in the same SQL dialect that's
easy to test with `psql`.

## Validation
Every view was created and queried against the real loaded dataset (150
accounts, 1,377 tickets) before being handed off for Power BI use:
- `vw_account_health`: 150 rows, exactly one per account.
- `vw_ticket_sla`: SLA breach rate 43.6% — plausible given the risk-profile
  weighting in the generator (`at_risk`/`critical` profiles get 2.2x-3.5x
  ticket volume and slower resolution).
- `vw_latest_survey`: exactly one row per account with a survey (150 = 150),
  confirming the `DISTINCT ON` dedup logic is correct.
- **Bug caught here, not in Power BI:** `renewal_date` is the account's
  single original renewal date and goes negative (into the past) for
  accounts that started 1+ years ago. Fixed by adding
  `next_renewal_date` / `days_to_next_renewal`, which roll the date forward
  to the next annual cycle. Verified 0 rows with negative
  `days_to_next_renewal` after the fix.

## Consequences
- Power BI's data model only needs relationships between these 6 views —
  no complex Power Query merges required.
- Any future refresh (new synthetic data, new risk logic) only requires
  re-running `psql -f sql/reporting_views.sql`; Power BI's model is
  untouched.
