# Customer Success Operations Intelligence Platform

An end-to-end customer operations analytics platform that integrates CRM,
support, product usage, survey, and renewal data into a unified model for
customer health monitoring, risk detection, SLA tracking, and CSM performance
analysis.

**Stack:** Python · PostgreSQL (Docker) · Pandas · SQLAlchemy · Power BI

---

## Why this project

Real customer-facing teams don't lack dashboards — they lack a single
operational view that connects the sales handoff, onboarding, support load,
satisfaction, and renewal risk of an account, and tells a CSM what to do
about it. This project builds that view from the ground up: schema design,
synthetic-but-realistic data, a transparent health-scoring engine, and
automated risk detection — not just a chart on top of a spreadsheet.

## Roadmap / Build phases

- [x] **Phase 1 — Data foundation**: relational schema, synthetic data
      generator with correlated risk patterns, Postgres loader.
- [x] **Phase 2 — Intelligence layer**: data quality checks, health score
      engine, risk/churn detection, Action Center. Validated: churned
      accounts score 36 pts lower on average than renewed ones (see
      `docs/decisions/002-scoring-engine.md`).
- [ ] **Phase 3 — Reporting**: SQL reporting views validated against live
      data (see `docs/decisions/003-reporting-views.md`), Power BI dashboards
      (Executive Overview, Customer Health, CSM Performance). Setup guide:
      `docs/powerbi_setup.md`.
- [x] **Phase 4 — Automation**: scheduled recalculation (`src/automation/scheduler.py`),
      delta-aware digest reports that only alert on what changed
      (`src/automation/notifier.py`), audit log of every run
      (`automation_runs` table). Found and fixed 3 real bugs during
      integration testing — see `docs/decisions/004-phase4-integration-bugs.md`.
- [x] **v2a — CSM Workload & Capacity Planning**: weighted workload score
      per CSM (`src/scoring/workload.py`), quartile-based Balanced /
      Elevated / High / Overloaded categories, written to `csm_workload`
      each run. Directly answers "which CSMs need headcount support" —
      see `docs/decisions/005-workload-planning.md`.
- [ ] **v2b (future work)**: incentive scorecards, SLA control tower.

Each phase gets its own branch, PR, and a short write-up in `docs/decisions/`.

## Data model

See [`docs/data_model.md`](docs/data_model.md) for the full entity
descriptions. Core tables: `accounts`, `contacts`, `opportunities`,
`customer_success` (sales→CS handoff + onboarding), `support_tickets`,
`product_usage`, `surveys`, `renewals`. Phase 2 adds `health_scores` and
`action_center`.

## Getting started

### 1. Start PostgreSQL

```bash
docker compose up -d
```

This starts Postgres on `localhost:5432` and automatically runs
`sql/schema.sql` on first boot (via `docker-entrypoint-initdb.d`).

### 2. Set up Python environment

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### 3. Generate synthetic data

```bash
python src/data_generation/generate_data.py --num-accounts 150
```

This writes CSVs to `data/generated/`. The generator assigns each account a
hidden risk profile (healthy / monitor / at-risk / critical) that drives
usage decline, ticket volume, CSAT, and renewal outcome together — so the
Phase 2 scoring engine has real signal to find, not noise.

### 4. Load data into Postgres

```bash
python src/etl/load_to_postgres.py
```

### 5. Verify

```bash
docker exec -it csops_postgres psql -U csops_admin -d csops -c "SELECT account_status, COUNT(*) FROM accounts GROUP BY 1;"
```

### 6. Run Phase 2 + v2: data quality, health scoring, workload planning

Apply the workload table migration first (once, on your existing volume):
```bash
docker cp sql/migrations/002_add_csm_workload.sql csops_postgres:/tmp/m2.sql
docker exec -it csops_postgres psql -U csops_admin -d csops -f /tmp/m2.sql
```

```bash
python src/scoring/run_scoring.py
```

This reads all tables from Postgres, prints a Data Quality Score, computes
health scores per account, writes them to `health_scores`, populates
`action_center` with recommended next steps for at-risk accounts, and
writes CSM workload/capacity scores to `csm_workload`.

### 7. Run the test suite

```bash
pytest tests/test_phase2.py -v
```

Includes the key validation check: churned accounts must score meaningfully
lower than renewed ones — proof the engine finds real signal, not noise.

### 8. Phase 3: Power BI dashboards

See [`docs/powerbi_setup.md`](docs/powerbi_setup.md) for the full connection
guide, DAX measures, dashboard specs, and a validation checklist with the
exact numbers your data should produce (e.g. SLA breach rate ≈ 43.6%,
30 Critical accounts) — confirmed against this project's live dataset so
you can catch a broken relationship in Power BI immediately instead of
guessing.

### 9. Phase 4: automation & scheduling

Apply the new `automation_runs` table (same reason as the views — Docker's
init scripts won't re-run automatically on your existing volume):
```bash
docker cp sql/migrations/001_add_automation_runs.sql csops_postgres:/tmp/m1.sql
docker exec -it csops_postgres psql -U csops_admin -d csops -f /tmp/m1.sql
```

Run the full pipeline (quality checks -> scoring -> action center -> digest)
once:
```bash
python src/automation/scheduler.py --once
```
This writes a Markdown digest to `data/reports/` that only flags **what
changed** since the last run (newly critical accounts, significant score
drops, action items due soon) — not the same list every day. It also logs
every run's outcome to the `automation_runs` table, success or failure.

**To schedule it daily**, on Windows use Task Scheduler (recommended — no
process needs to stay running):
1. Task Scheduler → Create Basic Task → Daily
2. Action: Start a program → `python.exe` (from your `venv\Scripts\`)
3. Arguments: `src\automation\scheduler.py --once`
4. Start in: your project folder

Or run it in the foreground for a live demo:
```bash
python src/automation/scheduler.py --daemon --time 06:00
```

Optional email alerts: set `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`,
`ALERT_EMAIL_TO` in `.env`. Without them, the digest file is still written —
email is silently skipped, not required.

## Project structure

```
├── docker-compose.yml       # Postgres container
├── sql/schema.sql            # Full relational schema
├── src/
│   ├── data_generation/      # Synthetic data generator
│   ├── etl/                  # Load scripts
│   ├── data_quality/         # Phase 2
│   ├── scoring/              # Phase 2: health score engine, v2: workload
│   └── automation/           # Phase 4: scheduler, alerts, Action Center
├── dashboards/                # Power BI files + exported screenshots
├── docs/
│   ├── architecture.md
│   ├── data_model.md
│   └── decisions/             # short design-decision notes per phase
└── tests/
```

## License

MIT
