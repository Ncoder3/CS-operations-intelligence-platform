# ADR 004 — Bugs Found During Phase 4 Integration Testing

**Date:** 2026-09-06
**Status:** Accepted

## Context
Before adding the automation layer, the full pipeline (fresh DB -> schema ->
views -> generate -> load -> score -> automate) was run end-to-end against
a clean database to validate the project as a whole, not just each phase in
isolation. This surfaced three real bugs.

## 1. Engagement score was bimodal (0 or 100, almost nothing between)

`score_engagement()` used `rank(pct=True)` on each account's own 12-month
usage window, then compared the average rank of the first 3 months to the
last 3. Ranking only 12 points forces them onto a fixed 1/12..12/12 ladder
regardless of the actual size of change — so an account with a genuinely
flat trend (just normal month-to-month noise) could still show its
"highest-ranked" months bunched at one end, producing a fake near-100%
swing after the `50 + pct_change*150` formula. Result: 64/150 accounts
scored exactly 0.

**Fix:** normalize each metric against the account's own mean instead of
ranking, so the early-vs-late comparison reflects actual magnitude of
change, not rank position. Verified: extreme (0 or 100) scores dropped from
146/150 to 61/150, with a real spread in between. Churn correlation held
(churned avg 41.8 vs renewed avg 75.6, gap ~34 pts) — actually a healthier
gap than before, since it's driven by real signal, not clipping artifacts.
Regression test added: `test_engagement_score_is_not_bimodal`.

## 2. docker-compose init script ordering

Mounting the whole `sql/` directory to `docker-entrypoint-initdb.d` lets
Postgres run files in **alphabetical** order: `reporting_views.sql` (r)
before `schema.sql` (s) — so a fresh `docker compose up` would fail trying
to create views over tables that don't exist yet. Only didn't surface
earlier because the running container already had data loaded (init
scripts only run once, on an empty volume).

**Fix:** mount the two files explicitly with numeric prefixes
(`1_schema.sql`, `2_views.sql`) so order is guaranteed regardless of
filename. Verified against a completely fresh database.

## 3. `numpy.int64` passed to psycopg2 array parameter

`notifier.py`'s `get_account_names()` passed a pandas-derived list of
`numpy.int64` directly into a `WHERE account_id = ANY(%(ids)s)` query.
psycopg2 can't adapt numpy int types (unlike SQLAlchemy's `to_sql`, which
handles this internally) — this only surfaces on the **second** automation
run, once there's a previous score to diff against and newly-critical/
score-drop account IDs actually get passed to this function. First-run
testing alone would not have caught it.

**Fix:** cast to native Python `int` before passing as a query parameter.
Verified by simulating a two-day run: manually degraded one account's
usage, backdated the prior run's `score_date`, and confirmed the digest
correctly isolated that one account as a score-drop while showing zero
false "newly critical" alerts for the other 29 already-known critical
accounts.

## Consequences
All three fixes are behavioral, not stylistic — each would have caused a
visible failure or silently wrong dashboard numbers for anyone running this
project fresh. This is why `docs/decisions/` exists: catching this now, in
writing, is worth more in an interview than a project that "just worked" on
one machine without anyone asking why.
