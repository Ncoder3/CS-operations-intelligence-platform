# ADR 005 — CSM Workload & Capacity Planning

**Date:** 2026-09-06
**Status:** Accepted

## Context
The original spec called for a workload score using fixed weights and a
fixed category cutoff (e.g. "score > 50 = Overloaded"). A fixed numeric
threshold is meaningless without knowing the scale of the underlying
portfolio — 50 points might be nothing for an 8-person team with 150
accounts and mean something completely different at 20x that scale.

## Decision
- Kept weighted scoring (active account=1, at-risk=2, critical=3, open
  ticket=0.5, upcoming renewal=1.5) — riskier accounts and open tickets
  cost more CSM attention than a routine healthy account.
- Replaced fixed score thresholds with **quartile-based categories**
  (`pd.qcut`), computed against the actual current distribution of CSM
  scores. "Overloaded" means top quartile of *this* portfolio, right now
  — which stays meaningful whether there are 8 CSMs or 80.
- Renewal proximity reused the exact rollover logic from
  `sql/reporting_views.sql` (`vw_account_health.days_to_next_renewal`),
  reimplemented in Python (`_add_days_to_next_renewal` in
  `run_scoring.py`) rather than depending on the view existing at
  pipeline-run time. Cross-validated: 0 mismatches across all 150 accounts
  between the SQL and Python implementations of the same rule.

## Validation
Ran against real data: produced a genuine spread (Overloaded: 57.0 down to
Balanced: 29.0 — no ties collapsing everyone into one bucket), and a
regression test (`test_workload_score_increases_with_risk`) confirms the
weighting direction is correct — swapping one account from Healthy to
Critical for an otherwise-identical CSM strictly increases their score.

## Consequences
- `qcut` can raise `ValueError` if there are fewer than 4 distinct score
  values (possible with a very small number of CSMs, or several tied
  scores) — handled with a median-split fallback rather than crashing the
  pipeline.
- Because categories are relative, "Overloaded" today doesn't mean the
  same absolute score next month if the portfolio grows — which is the
  intended behavior for capacity planning, but worth stating explicitly
  since it means quarter-over-quarter score comparisons should look at
  the workload_score number, not just the category label.
