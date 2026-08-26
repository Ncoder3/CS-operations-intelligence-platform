-- ============================================================
-- Customer Success Operations Intelligence Platform
-- Core relational schema (Phase 1)
-- ============================================================

CREATE TABLE IF NOT EXISTS accounts (
    account_id       SERIAL PRIMARY KEY,
    company_name      VARCHAR(255) NOT NULL,
    industry          VARCHAR(100),
    segment           VARCHAR(50),          -- Enterprise / Mid-Market / SMB
    region            VARCHAR(100),
    csm_owner         VARCHAR(100),          -- assigned Customer Success Manager
    account_status    VARCHAR(50),           -- Active / Churned / Onboarding
    contract_value    NUMERIC(12, 2),
    start_date        DATE,
    renewal_date      DATE
);

CREATE TABLE IF NOT EXISTS contacts (
    contact_id        SERIAL PRIMARY KEY,
    account_id        INTEGER REFERENCES accounts(account_id) ON DELETE CASCADE,
    full_name         VARCHAR(255),
    role              VARCHAR(100),
    department        VARCHAR(100),
    engagement_status VARCHAR(50)            -- Active / Inactive
);

CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id    SERIAL PRIMARY KEY,
    account_id        INTEGER REFERENCES accounts(account_id) ON DELETE CASCADE,
    sales_owner       VARCHAR(100),
    opportunity_stage VARCHAR(50),
    amount            NUMERIC(12, 2),
    close_date        DATE,
    outcome           VARCHAR(50)            -- Won / Lost
);

-- Sales -> CS handoff record, one per won opportunity
CREATE TABLE IF NOT EXISTS customer_success (
    account_id        INTEGER PRIMARY KEY REFERENCES accounts(account_id) ON DELETE CASCADE,
    csm_owner         VARCHAR(100),
    handoff_created_at    TIMESTAMP,
    handoff_accepted_at   TIMESTAMP,
    onboarding_status     VARCHAR(50),       -- Not Started / In Progress / Complete
    onboarding_started_at TIMESTAMP,
    onboarding_completed_at TIMESTAMP,
    success_plan          TEXT,
    health_status          VARCHAR(50)        -- populated by scoring engine (Phase 2)
);

CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id         SERIAL PRIMARY KEY,
    account_id        INTEGER REFERENCES accounts(account_id) ON DELETE CASCADE,
    priority          VARCHAR(20),           -- Low / Medium / High / Critical
    category          VARCHAR(100),
    created_date      TIMESTAMP,
    resolved_date     TIMESTAMP,
    sla_hours         INTEGER,               -- SLA target in hours
    status            VARCHAR(50)            -- Open / Resolved / Escalated
);

CREATE TABLE IF NOT EXISTS product_usage (
    usage_id          SERIAL PRIMARY KEY,
    account_id        INTEGER REFERENCES accounts(account_id) ON DELETE CASCADE,
    usage_date        DATE,
    sessions          INTEGER,
    active_users      INTEGER,
    feature_usage_pct NUMERIC(5, 2)          -- % of licensed features actively used
);

CREATE TABLE IF NOT EXISTS surveys (
    survey_id         SERIAL PRIMARY KEY,
    account_id        INTEGER REFERENCES accounts(account_id) ON DELETE CASCADE,
    survey_date       DATE,
    csat_score        NUMERIC(5, 2),         -- 0-100
    nps_score         INTEGER,               -- -100 to 100
    feedback_category VARCHAR(100)           -- Support / Product / Onboarding / Billing / Other
);

CREATE TABLE IF NOT EXISTS renewals (
    renewal_id        SERIAL PRIMARY KEY,
    account_id        INTEGER REFERENCES accounts(account_id) ON DELETE CASCADE,
    renewal_date      DATE,
    renewal_value     NUMERIC(12, 2),
    renewal_status    VARCHAR(50),           -- Renewed / Churned / Pending / At Risk
    churn_reason      VARCHAR(255)
);

-- ============================================================
-- Phase 2 tables: populated by the scoring/automation layer,
-- not by raw data generation. Created here so the schema is
-- complete from day one.
-- ============================================================

CREATE TABLE IF NOT EXISTS health_scores (
    account_id        INTEGER REFERENCES accounts(account_id) ON DELETE CASCADE,
    score_date        DATE,
    engagement_score  NUMERIC(5, 2),
    support_score     NUMERIC(5, 2),
    csat_score        NUMERIC(5, 2),
    nps_score         NUMERIC(5, 2),
    onboarding_score  NUMERIC(5, 2),
    overall_score     NUMERIC(5, 2),
    health_status     VARCHAR(20),           -- Healthy / Monitor / At Risk / Critical
    risk_drivers      TEXT,                  -- human-readable "why" for the score
    PRIMARY KEY (account_id, score_date)
);

CREATE TABLE IF NOT EXISTS action_center (
    action_id         SERIAL PRIMARY KEY,
    account_id        INTEGER REFERENCES accounts(account_id) ON DELETE CASCADE,
    risk_level        VARCHAR(20),
    reason            TEXT,
    recommended_action TEXT,
    owner             VARCHAR(100),
    due_date          DATE,
    status            VARCHAR(50) DEFAULT 'Open',
    created_at        TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tickets_account ON support_tickets(account_id);
CREATE INDEX IF NOT EXISTS idx_usage_account_date ON product_usage(account_id, usage_date);
CREATE INDEX IF NOT EXISTS idx_surveys_account ON surveys(account_id);
CREATE INDEX IF NOT EXISTS idx_renewals_account ON renewals(account_id);
