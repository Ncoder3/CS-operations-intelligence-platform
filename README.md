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
- [ ] **Phase 2 — Intelligence layer**: data quality checks, health score
      engine, risk/churn detection.
- [ ] **Phase 3 — Reporting**: Power BI dashboards (Executive Overview,
      Customer Health, CSM Performance).
- [ ] **Phase 4 — Automation**: scheduled recalculation, SLA breach
      detection, Action Center queue.
- [ ] **v2 (future work)**: CSM workload/capacity planning, incentive
      scorecards, SLA control tower.

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

## Project structure

```
├── docker-compose.yml       # Postgres container
├── sql/schema.sql            # Full relational schema
├── src/
│   ├── data_generation/      # Synthetic data generator
│   ├── etl/                  # Load scripts
│   ├── data_quality/         # Phase 2
│   ├── scoring/              # Phase 2: health score engine
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
