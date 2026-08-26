# Power BI Setup & Dashboard Guide (Phase 3)

## 0. Apply the views to your existing database

Your Postgres container already has data loaded, so the new
`sql/reporting_views.sql` won't auto-run via Docker init. Apply it manually
once:

```bash
docker cp sql/reporting_views.sql csops_postgres:/tmp/views.sql
docker exec -it csops_postgres psql -U csops_admin -d csops -f /tmp/views.sql
```

Verify:
```bash
docker exec -it csops_postgres psql -U csops_admin -d csops -c "\dv"
```
You should see 6 views listed.

## 1. Install the PostgreSQL connector for Power BI

Power BI Desktop needs the **Npgsql** data provider to connect to Postgres:

1. Download the latest `Npgsql` release from the official repo:
   https://github.com/npgsql/npgsql/releases (get the `.msi`, not the source).
2. Run the installer, then **restart Power BI Desktop** if it was open.

## 2. Connect Power BI to the database

1. Power BI Desktop → **Get Data** → search "PostgreSQL database"
2. Server: `localhost:5432`, Database: `csops`
3. Data Connectivity mode: **Import** (not DirectQuery — this is a small
   dataset and Import gives you offline/faster performance)
4. Credentials: Username `csops_admin`, Password `csops_pass` (or whatever
   you set in `.env`)
5. In the Navigator, select only the 6 views (`vw_account_health`,
   `vw_ticket_sla`, `vw_usage_trend`, `vw_latest_survey`,
   `vw_csm_performance`, `vw_action_center`) — **not** the raw tables.
   Click **Transform Data** to open Power Query first (so you can fix
   column types before loading) rather than Load directly.
6. In Power Query: confirm `overall_score`, `csat_score` etc. are typed as
   Decimal Number, and all `*_date` columns are typed as Date — Npgsql
   sometimes imports dates as text. Fix with the column type selector if
   needed. Then **Close & Apply**.

## 3. Build the data model (Model view)

`vw_account_health` is your central table. Create relationships:

- `vw_account_health[account_id]` → `vw_ticket_sla[account_id]` (1 to many)
- `vw_account_health[account_id]` → `vw_usage_trend[account_id]` (1 to many)
- `vw_account_health[account_id]` → `vw_action_center[account_id]` (1 to many)
- `vw_account_health[csm_owner]` → `vw_csm_performance[csm_owner]` (1 to many)

All relationships: single direction, `vw_account_health` as the "one" side.

**Sanity check before building visuals:** add a blank card visual with
`COUNTROWS(vw_account_health)` — it must read **150**. If it reads higher,
a relationship is fanning out rows; if lower, a join in the view is
dropping accounts. Do this check after every relationship you add, not
just at the end.

## 4. Core DAX measures to create

In `vw_account_health`, add a new table of measures (right-click table →
New Measure):

```dax
Total Accounts = COUNTROWS(vw_account_health)

Healthy Accounts = CALCULATE([Total Accounts], vw_account_health[health_status] = "Healthy")
At Risk Accounts = CALCULATE([Total Accounts], vw_account_health[health_status] = "At Risk")
Critical Accounts = CALCULATE([Total Accounts], vw_account_health[health_status] = "Critical")

Avg Health Score = AVERAGE(vw_account_health[overall_score])
Avg CSAT = AVERAGE(vw_account_health[csat_score])
Avg NPS = AVERAGE(vw_account_health[nps_score])

Retention Rate =
DIVIDE(
    CALCULATE([Total Accounts], vw_account_health[renewal_status] = "Renewed"),
    CALCULATE([Total Accounts], vw_account_health[renewal_status] IN {"Renewed","Churned"})
)

Total Portfolio Value = SUM(vw_account_health[contract_value])

Open Tickets = CALCULATE(COUNTROWS(vw_ticket_sla), vw_ticket_sla[status] = "Open")
SLA Breach Rate = DIVIDE(
    CALCULATE(COUNTROWS(vw_ticket_sla), vw_ticket_sla[sla_breached] = TRUE),
    COUNTROWS(vw_ticket_sla)
)
```

**Validate each measure as you add it** against the psql output you already
have. E.g. `SLA Breach Rate` on a card visual should show ~43.6% — matches
the number I validated directly against Postgres. If Power BI shows
something wildly different, the bug is in the relationship/model, not the
underlying data.

## 5. The three dashboards

### Dashboard 1 — Executive Overview
- KPI cards: Total Accounts, Healthy/At Risk/Critical counts, Avg Health
  Score, Retention Rate, Total Portfolio Value, Open Tickets
- Donut chart: accounts by `health_status`
- Bar chart: accounts by `segment`
- Table: upcoming renewals (`vw_account_health` filtered to
  `days_to_next_renewal <= 90`, sorted ascending)

### Dashboard 2 — Customer Health
- Table/matrix: `vw_action_center` (account, risk_level, reason,
  recommended_action, owner, due_date) — this is the operational view
- Scatter: `overall_score` (x) vs `contract_value` (y), colored by
  `health_status` — surfaces high-value at-risk accounts immediately
- Line chart: `vw_usage_trend[sessions]` over `usage_date`, filterable by
  account
- Bar: average score by `industry` or `region`

### Dashboard 3 — CSM Performance
- Table from `vw_csm_performance`: csm_owner, total_accounts,
  critical_accounts, avg_health_score, open_tickets, total_portfolio_value
- Bar chart: critical_accounts by csm_owner (sorted descending — surfaces
  who needs help first)
- Card: portfolio value per CSM

## 6. Save and commit

Save as `dashboards/csops_platform.pbix`. Also export each dashboard page
as PNG (File → Export → Export to PDF, or screenshot) into
`dashboards/screenshots/` — these are what a reviewer sees on GitHub
without opening Power BI.

```bash
git add dashboards/
git commit -m "Phase 3: Power BI dashboards (Executive, Customer Health, CSM Performance)"
git tag v0.3-dashboards
```

## 7. What "correct" looks like — checklist before moving on

- [ ] Card visual `COUNTROWS(vw_account_health)` = 150, matches your accounts table
- [ ] `[SLA Breach Rate]` ≈ 43.6% (matches the psql validation above)
- [ ] `[Critical Accounts]` = 30 (matches `run_scoring.py` output)
- [ ] `vw_action_center` table row count = 67 (30 Critical + 32 At Risk + 5 Monitor)
- [ ] No visual shows blank/(Blank) categories for `health_status` or `csm_owner` — that means a join is failing
- [ ] Filtering Dashboard 3 by a single CSM and cross-checking their
      `critical_accounts` count against a manual
      `SELECT COUNT(*) FROM vw_account_health WHERE csm_owner = '...' AND health_status = 'Critical'`
