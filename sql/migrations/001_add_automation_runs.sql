-- Migration for existing databases (Docker init scripts only run on an
-- empty volume, so if you already loaded data, apply this manually):
--
--   docker cp sql/migrations/001_add_automation_runs.sql csops_postgres:/tmp/m1.sql
--   docker exec -it csops_postgres psql -U csops_admin -d csops -f /tmp/m1.sql

CREATE TABLE IF NOT EXISTS automation_runs (
    run_id                SERIAL PRIMARY KEY,
    run_started_at        TIMESTAMP,
    run_completed_at      TIMESTAMP,
    status                VARCHAR(20),
    data_quality_score    NUMERIC(5, 2),
    total_accounts        INTEGER,
    healthy_count         INTEGER,
    monitor_count         INTEGER,
    at_risk_count         INTEGER,
    critical_count        INTEGER,
    action_items_created  INTEGER,
    error_message         TEXT
);
