-- Migration for existing databases (apply manually, same reason as 001):
--
--   docker cp sql/migrations/002_add_csm_workload.sql csops_postgres:/tmp/m2.sql
--   docker exec -it csops_postgres psql -U csops_admin -d csops -f /tmp/m2.sql

CREATE TABLE IF NOT EXISTS csm_workload (
    csm_owner           VARCHAR(100),
    run_date            DATE,
    total_accounts      INTEGER,
    at_risk_accounts    INTEGER,
    critical_accounts   INTEGER,
    open_tickets        INTEGER,
    upcoming_renewals   INTEGER,
    workload_score      NUMERIC(6, 1),
    workload_category   VARCHAR(20),
    PRIMARY KEY (csm_owner, run_date)
);
