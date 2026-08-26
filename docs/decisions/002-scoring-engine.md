# ADR 002 — Health Score Engine Design

**Date:** 2026-08-26
**Status:** Accepted

## Context
The original spec called for 6 score components including "Renewal Proximity"
(15%) and "Payment/Account Status" (10%).

## Decision
Dropped both in favor of a 5-component model:
Engagement 25% · Support 20% · CSAT 20% · NPS 15% · Onboarding/Handoff 20%.

## Why
- **Renewal Proximity as a score input is circular.** `renewal_status` /
  `churn_reason` in this dataset represent a known outcome (renewed vs.
  churned), not a leading indicator available at scoring time. Feeding it
  into the score would let the score partly explain itself, inflating
  apparent accuracy without adding real signal. Instead, renewal proximity
  is used downstream as an **urgency multiplier** in the Action Center
  (`src/scoring/run_scoring.py::build_action_center`) — an account within
  60 days of renewal gets escalated due dates, but its *score* is untouched.
- **Payment/Account status** isn't modeled in this dataset (no billing
  system), so a component here would just be a constant — not real signal.
- **Onboarding/Handoff Health** replaces them because it's a genuine
  measurable leading indicator (handoff delay, onboarding duration vs. SLA)
  and directly reflects the Sales -> CS handoff workflow the source spec
  emphasized as a differentiator.

## Validation
`tests/test_phase2.py::test_health_score_correlates_with_actual_churn`
checks that churned accounts score meaningfully lower (>10 pts) on average
than renewed accounts, using `renewal_status` purely as a held-out check —
never as a model input. On the current synthetic dataset: churned avg 40.9
vs. renewed avg 76.7.

## Consequences
- Score is honestly a leading-indicator score, defensible in an interview:
  "the score doesn't know the outcome, and it still separates outcomes by
  36 points."
- `health_scores.overall_score` sums to component weights that are visible
  and testable (`WEIGHTS` constant in `src/scoring/health_score.py`), not
  buried in SQL.
