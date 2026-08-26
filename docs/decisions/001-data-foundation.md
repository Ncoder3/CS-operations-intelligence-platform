# ADR 001 — Data Foundation

**Date:** 2026-08-26
**Status:** Accepted

## Context
Needed a realistic CRM + Customer Success dataset to build the platform on,
without access to real company data.

## Decision
Generate synthetic data in Python (`Faker` + custom logic) where each account
is assigned a hidden risk profile (`healthy / monitor / at_risk / critical`)
that deterministically influences usage trend, ticket volume/severity, CSAT
range, and renewal/churn outcome. The profile itself is never written to the
output data — it only exists to make the generated data internally
consistent, the way real operational data is.

## Why not use a public dataset instead
No public dataset models the sales -> CS handoff -> onboarding -> support ->
renewal workflow this project is built around. Public support-ticket or churn
datasets exist in isolation and wouldn't let the health-score engine
cross-reference usage, tickets, and survey data for the same account.

## Consequences
- Anyone reviewing the repo can regenerate the exact same dataset
  (`Faker.seed(42)`), which makes the project reproducible and the scoring
  results explainable.
- The README and this ADR explicitly disclose that the data is synthetic —
  important for interview credibility.
